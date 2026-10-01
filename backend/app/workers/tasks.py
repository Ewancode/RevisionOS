"""Background tasks run by the Arq worker."""

import uuid
from typing import Any

from app.ingestion.pipeline import Deps, process_document, retranscribe_page


async def ping(ctx: dict[str, Any]) -> str:
    """Round-trip check that the worker is consuming the queue."""
    return "pong"


async def process_document_job(ctx: dict[str, Any], document_id: str) -> None:
    deps: Deps = ctx["deps"]
    await process_document(deps, uuid.UUID(document_id))


async def retranscribe_page_job(ctx: dict[str, Any], document_id: str, page_no: int) -> None:
    deps: Deps = ctx["deps"]
    await retranscribe_page(deps, uuid.UUID(document_id), page_no)
