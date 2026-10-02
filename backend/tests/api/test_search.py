"""Indexing and hybrid search, end to end (embeddings from the hashing test
provider, so no model download)."""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.ingestion.pipeline import Deps, reindex_document
from app.models import Chunk
from app.models.retrieval import EMBEDDING_DIMENSIONS
from app.retrieval.search import SearchService
from tests import factories
from tests.fakes import RecordingQueue
from tests.support import create_module, ingest, make_user, signed_in

pytestmark = pytest.mark.db

LECTURE = [
    "Black-Scholes assumptions: the underlying follows geometric Brownian motion, "
    "volatility and the risk-free rate are constant, and there are no dividends.",
    "Integration by parts follows from the product rule for derivatives.",
    "The Central Limit Theorem says sample means are approximately normal.",
]


def test_embedding_dimensions_match_the_database_column() -> None:
    assert get_config().retrieval.embeddings.dimensions == EMBEDDING_DIMENSIONS


@pytest.fixture
async def client(db_app: FastAPI, db: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    async with signed_in(db_app, await make_user(db)) as c:
        yield c


async def _search(client: httpx.AsyncClient, q: str, **scope: str) -> dict[str, Any]:
    response = await client.get("/api/v1/search", params={"q": q, **scope})
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_processing_indexes_every_page(
    client: httpx.AsyncClient, deps: Deps, queue: RecordingQueue, db: AsyncSession, tmp_path: Path
) -> None:
    module = await create_module(client)
    doc_id = await ingest(
        client, deps, queue, module["id"], factories.pdf(tmp_path / "x", LECTURE), "w3.pdf"
    )

    pages = (
        await db.scalars(
            select(Chunk.page_no)
            .where(Chunk.document_id == uuid.UUID(doc_id))
            .order_by(Chunk.page_no)
        )
    ).all()
    assert pages == [1, 2, 3]
    doc = (await client.get(f"/api/v1/documents/{doc_id}")).json()
    assert (doc["status"], doc["error_code"]) == ("ready", None)


async def test_search_finds_the_right_page_and_links_to_it(
    client: httpx.AsyncClient, deps: Deps, queue: RecordingQueue, tmp_path: Path
) -> None:
    module = await create_module(client)
    doc_id = await ingest(
        client, deps, queue, module["id"], factories.pdf(tmp_path / "x", LECTURE), "w3.pdf"
    )

    # A natural question: most of its words are not in the passage (OR, not AND).
    result = await _search(client, "what does Black-Scholes assume about volatility?")
    top = result["passages"][0]
    assert (top["document_id"], top["page_no"]) == (doc_id, 1)
    assert top["filename"] == "w3.pdf"
    assert top["module_code"] == "MATH260"
    assert top["matched"] in ("keyword", "both")
    assert result["scope_used"] == "all"


async def test_one_result_per_page(
    client: httpx.AsyncClient, deps: Deps, queue: RecordingQueue, tmp_path: Path
) -> None:
    module = await create_module(client)
    long_page = "\n\n".join(
        f"Paragraph {i} about integration by parts. " + "x " * 120 for i in range(6)
    )
    await ingest(
        client, deps, queue, module["id"], factories.pdf(tmp_path / "x", [long_page]), "a.pdf"
    )
    passages = (await _search(client, "integration by parts"))["passages"]
    keys = [(p["document_id"], p["page_no"]) for p in passages]
    assert len(keys) == len(set(keys))


async def test_names_of_modules_topics_and_files_are_searched(
    client: httpx.AsyncClient, deps: Deps, queue: RecordingQueue, tmp_path: Path
) -> None:
    module = await create_module(client)
    await client.post(f"/api/v1/modules/{module['id']}/topics", json={"title": "Option pricing"})
    await ingest(
        client,
        deps,
        queue,
        module["id"],
        factories.pdf(tmp_path / "x", LECTURE),
        "Option notes.pdf",
    )

    result = await _search(client, "option")
    assert [t["title"] for t in result["topics"]] == ["Option pricing"]
    assert [d["original_filename"] for d in result["documents"]] == ["Option notes.pdf"]
    assert [m["code"] for m in (await _search(client, "financial"))["modules"]] == ["MATH260"]


async def test_scoped_search_widens_when_it_finds_too_little(
    client: httpx.AsyncClient, deps: Deps, queue: RecordingQueue, tmp_path: Path
) -> None:
    finance = await create_module(client, "MATH260")
    calculus = await create_module(client, "MATH101")
    await ingest(
        client, deps, queue, finance["id"], factories.pdf(tmp_path / "x", LECTURE), "fin.pdf"
    )

    scoped = await _search(client, "Central Limit Theorem", module_id=calculus["id"])
    assert scoped["widened"] is True
    assert scoped["scope_used"] == "all"
    assert scoped["passages"][0]["module_code"] == "MATH260"

    # In-scope hits come first; nothing wider exists, so nothing is added.
    inside = await _search(client, "Central Limit Theorem", module_id=finance["id"])
    assert (inside["widened"], inside["scope_used"]) == (False, "module")
    assert inside["passages"][0]["page_no"] == 3


async def test_deleted_documents_disappear_from_search_until_restored(
    client: httpx.AsyncClient, deps: Deps, queue: RecordingQueue, tmp_path: Path
) -> None:
    module = await create_module(client)
    doc_id = await ingest(
        client, deps, queue, module["id"], factories.pdf(tmp_path / "x", LECTURE), "a.pdf"
    )
    await client.delete(f"/api/v1/documents/{doc_id}")
    assert (await _search(client, "Black-Scholes volatility"))["passages"] == []
    await client.post(f"/api/v1/documents/{doc_id}/restore")
    assert (await _search(client, "Black-Scholes volatility"))["passages"]


async def test_corrections_reindex_only_that_page(
    client: httpx.AsyncClient,
    deps: Deps,
    queue: RecordingQueue,
    db: AsyncSession,
    tmp_path: Path,
) -> None:
    module = await create_module(client)
    doc_id = await ingest(
        client, deps, queue, module["id"], factories.pdf(tmp_path / "x", LECTURE), "a.pdf"
    )
    page3_before = await db.scalar(
        select(Chunk.id).where(Chunk.document_id == uuid.UUID(doc_id), Chunk.page_no == 3)
    )

    await client.put(
        f"/api/v1/documents/{doc_id}/pages/2", json={"markdown": "Itô's lemma for SDEs."}
    )
    [(name, args)] = queue.jobs
    assert (name, args[1]) == ("reindex_document", [2])
    queue.jobs.clear()
    await reindex_document(deps, uuid.UUID(doc_id), args[1])

    assert (await _search(client, "Itô lemma"))["passages"][0]["page_no"] == 2
    assert not [p for p in (await _search(client, "product rule"))["passages"] if p["page_no"] == 2]
    page3_after = await db.scalar(
        select(Chunk.id).where(Chunk.document_id == uuid.UUID(doc_id), Chunk.page_no == 3)
    )
    assert page3_after == page3_before  # untouched pages keep their chunks


async def test_topic_changes_reach_the_chunks(
    client: httpx.AsyncClient, deps: Deps, queue: RecordingQueue, db: AsyncSession, tmp_path: Path
) -> None:
    module = await create_module(client)
    topic = (
        await client.post(f"/api/v1/modules/{module['id']}/topics", json={"title": "Options"})
    ).json()
    doc_id = await ingest(
        client, deps, queue, module["id"], factories.pdf(tmp_path / "x", LECTURE), "a.pdf"
    )

    await client.patch(f"/api/v1/documents/{doc_id}", json={"topic_id": topic["id"]})
    topics = set(
        (
            await db.scalars(select(Chunk.topic_id).where(Chunk.document_id == uuid.UUID(doc_id)))
        ).all()
    )
    assert topics == {uuid.UUID(topic["id"])}
    scoped = await _search(client, "Black-Scholes volatility", topic_id=topic["id"])
    assert scoped["scope_used"] == "topic"


async def test_search_never_returns_another_users_material(
    db_app: FastAPI, db: AsyncSession, deps: Deps, queue: RecordingQueue, tmp_path: Path
) -> None:
    owner, other = (
        await make_user(db, "a@example.com", "A"),
        await make_user(db, "b@example.com", "B"),
    )
    async with signed_in(db_app, owner) as a, signed_in(db_app, other, ip="192.0.2.5") as b:
        module = await create_module(a)
        await ingest(
            a, deps, queue, module["id"], factories.pdf(tmp_path / "x", LECTURE), "secret.pdf"
        )
        result = await _search(b, "Black-Scholes volatility")
    assert result["passages"] == [] and result["documents"] == [] and result["modules"] == []


async def test_query_validation_and_empty_queries(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/search", params={"q": ""})).status_code == 422
    assert (await client.get("/api/v1/search", params={"q": "x" * 301})).status_code == 422
    # Only stop words: no keyword terms at all, still a clean (empty) answer.
    assert (await _search(client, "the of and"))["passages"] == []


async def test_index_failure_leaves_pages_readable(
    client: httpx.AsyncClient, deps: Deps, queue: RecordingQueue, tmp_path: Path
) -> None:
    class Broken:
        model_name = "broken"
        dimensions = EMBEDDING_DIMENSIONS

        async def embed_passages(self, texts: Any) -> Any:
            raise RuntimeError("model download failed")

        async def embed_query(self, text: str) -> Any:
            raise RuntimeError("model download failed")

    deps.embedder = Broken()
    module = await create_module(client)
    doc_id = await ingest(
        client, deps, queue, module["id"], factories.pdf(tmp_path / "x", LECTURE), "a.pdf"
    )
    doc = (await client.get(f"/api/v1/documents/{doc_id}")).json()
    assert (doc["status"], doc["error_code"]) == ("ready", "index_failed")
    assert len((await client.get(f"/api/v1/documents/{doc_id}/pages")).json()) == 3


async def test_fusion_weights_and_the_relevance_floor(db: AsyncSession) -> None:
    config = get_config().retrieval.search
    service = SearchService(db, uuid.uuid4(), None, config)  # type: ignore[arg-type]
    a, b, c, d = (uuid.uuid4() for _ in range(4))
    fused = service.fuse(
        keyword=[a, b],
        vector=[(b, 0.9), (c, 0.8), (d, config.min_vector_similarity - 0.01)],
    )
    order = [chunk_id for chunk_id, _, _ in fused]
    assert order[0] == b  # found by both
    assert d not in order  # meaning-only and below the floor
    matched = {chunk_id: m for chunk_id, _, m in fused}
    assert (matched[a], matched[b], matched[c]) == ("keyword", "both", "meaning")
    # A meaning-rank-1 hit outranks a keyword-rank-1 hit at keyword weight < 1.
    solo = service.fuse(keyword=[a], vector=[(c, 0.9)])
    assert [x for x, _, _ in solo] == [c, a]
    assert await db.scalar(select(func.count()).select_from(Chunk)) == 0
