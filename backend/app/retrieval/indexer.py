"""Build and refresh a document's searchable chunks (ARCHITECTURE.md section 7,
steps 3-5)."""

import uuid
from collections.abc import Iterable

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import RetrievalConfig
from app.models import Chunk, Document, DocumentPage, Module
from app.retrieval.chunking import chunk_document
from app.retrieval.embeddings import EmbeddingProvider


def embedding_text(module: Module, doc: Document, heading_path: str, content: str) -> str:
    """What is embedded: the chunk plus a short context header, so a chunk that
    only says "multiply by the conjugate" is still found for "complex division"."""
    header = " — ".join(
        p for p in (f"{module.code} {module.title}", doc.original_filename, heading_path) if p
    )
    return f"{header}\n\n{content}"


async def index_document(
    db: AsyncSession,
    embedder: EmbeddingProvider,
    config: RetrievalConfig,
    document_id: uuid.UUID,
    pages: Iterable[int] | None = None,
) -> int:
    """(Re)build chunks for the whole document, or only for `pages`.

    The whole document is always chunked, because headings carry across
    pages, but only the selected pages' chunks are re-embedded and replaced.
    Returns the number of chunks written.
    """
    doc = await db.get(Document, document_id)
    if doc is None:
        return 0
    module = await db.get(Module, doc.module_id)
    assert module is not None  # noqa: S101  # enforced by foreign key
    rows = (
        await db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_no)
        )
    ).all()
    selected = set(pages) if pages is not None else None
    chunks = [
        c
        for c in chunk_document(((r.page_no, r.markdown) for r in rows), config.chunking)
        if selected is None or c.page_no in selected
    ]
    vectors = await embedder.embed_passages(
        [embedding_text(module, doc, c.heading_path, c.content) for c in chunks]
    )

    stale = delete(Chunk).where(Chunk.document_id == document_id)
    if selected is not None:
        stale = stale.where(Chunk.page_no.in_(selected))
    await db.execute(stale)
    db.add_all(
        Chunk(
            user_id=doc.user_id,
            document_id=doc.id,
            module_id=doc.module_id,
            topic_id=doc.topic_id,
            source_tier=doc.source_tier,
            page_no=c.page_no,
            position=c.position,
            heading_path=c.heading_path,
            content=c.content,
            token_estimate=c.token_estimate,
            embedding=vector,
            embedding_model=embedder.model_name,
        )
        for c, vector in zip(chunks, vectors, strict=True)
    )
    await db.commit()
    return len(chunks)


async def sync_document_metadata(db: AsyncSession, doc: Document) -> None:
    """Keep the copies of topic and source tier on chunks in step with the
    document after an edit (no re-embedding needed)."""
    await db.execute(
        update(Chunk)
        .where(Chunk.document_id == doc.id)
        .values(topic_id=doc.topic_id, source_tier=doc.source_tier)
    )
