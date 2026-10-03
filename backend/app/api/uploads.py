"""Receiving raw-body uploads (files, answer photos) safely."""

import asyncio
from pathlib import Path

from fastapi import Request

from app.core.errors import AppError

CHUNK = 1024 * 1024


async def receive_to_file(request: Request, limit: int, target: Path) -> None:
    """Stream the raw request body to disk, refusing more than `limit` bytes
    whatever Content-Length claims."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise AppError("file_too_large", f"Uploads are limited to {limit // CHUNK} MB.", 413)
    received = 0
    with target.open("wb") as handle:
        async for chunk in request.stream():
            received += len(chunk)
            if received > limit:
                raise AppError(
                    "file_too_large", f"Uploads are limited to {limit // CHUNK} MB.", 413
                )
            await asyncio.to_thread(handle.write, chunk)
