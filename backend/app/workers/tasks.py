"""Background tasks. Real jobs (extraction, embedding, recomputation) arrive
with the phases that need them."""

from typing import Any


async def ping(ctx: dict[str, Any]) -> str:
    """Round-trip check that the worker is consuming the queue."""
    return "pong"
