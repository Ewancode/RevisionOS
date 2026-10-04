"""Background tasks run by the Arq worker."""

import uuid
from typing import Any

from app.ingestion.pipeline import Deps, process_document, reindex_document, retranscribe_page
from app.learning.summary import summarise
from app.practice.generation import run_draft
from app.practice.marking import mark_attempt


async def ping(ctx: dict[str, Any]) -> str:
    """Round-trip check that the worker is consuming the queue."""
    return "pong"


async def process_document_job(ctx: dict[str, Any], document_id: str) -> None:
    deps: Deps = ctx["deps"]
    await process_document(deps, uuid.UUID(document_id))


async def retranscribe_page_job(ctx: dict[str, Any], document_id: str, page_no: int) -> None:
    deps: Deps = ctx["deps"]
    await retranscribe_page(deps, uuid.UUID(document_id), page_no)


async def reindex_document_job(
    ctx: dict[str, Any], document_id: str, pages: list[int] | None = None
) -> None:
    deps: Deps = ctx["deps"]
    await reindex_document(deps, uuid.UUID(document_id), pages)


async def generate_draft_job(ctx: dict[str, Any], draft_id: str) -> None:
    deps: Deps = ctx["deps"]
    async with deps.sessions() as db:
        await run_draft(db, deps.claude, deps.embedder, deps.config, uuid.UUID(draft_id))


async def mark_attempt_job(ctx: dict[str, Any], attempt_id: str) -> None:
    deps: Deps = ctx["deps"]
    async with deps.sessions() as db:
        await mark_attempt(db, deps.claude, deps.config, uuid.UUID(attempt_id))


async def summarise_profile_job(ctx: dict[str, Any], snapshot_id: int) -> None:
    deps: Deps = ctx["deps"]
    async with deps.sessions() as db:
        await summarise(db, deps.claude, deps.config, snapshot_id)
