"""Rebuild search chunks for every live document (all users).

Usage: ``make reindex`` (or ``python -m scripts.reindex``). Needed after
changing the embedding model or the chunking settings, and once for documents
uploaded before search existed. Safe to re-run: each document's chunks are
replaced in one transaction.
"""

import asyncio
import sys
import time

from sqlalchemy import select

from app.core.config import get_config
from app.core.settings import get_settings
from app.db.session import create_engine, create_session_factory
from app.models import Document
from app.retrieval.embeddings import create_provider
from app.retrieval.indexer import index_document


async def main() -> int:
    settings = get_settings()
    config = get_config()
    engine = create_engine(settings.database_url.get_secret_value())
    embedder = create_provider(config.retrieval.embeddings, settings.model_cache_dir)
    sessions = create_session_factory(engine)
    try:
        async with sessions() as db:
            docs = (
                await db.execute(
                    select(Document.id, Document.original_filename)
                    .where(Document.deleted_at.is_(None))
                    .order_by(Document.created_at)
                )
            ).all()
        print(f"Indexing {len(docs)} documents with {embedder.model_name}...")
        for doc_id, name in docs:
            started = time.perf_counter()
            async with sessions() as db:
                count = await index_document(db, embedder, config.retrieval, doc_id)
            print(f"  {name}: {count} chunks ({time.perf_counter() - started:.1f}s)")
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
