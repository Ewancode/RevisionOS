"""The worker side of exports and restores."""

import logging
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.core.clock import utcnow
from app.core.errors import AppError
from app.export.archive import build_export
from app.export.restore import restore_archive
from app.ingestion.pipeline import Deps
from app.models import DataJob
from app.storage.base import archive_key

logger = logging.getLogger(__name__)

Enqueue = Callable[[str, str], Awaitable[None]]


async def _start(deps: Deps, job_id: uuid.UUID) -> DataJob | None:
    async with deps.sessions() as db:
        job = await db.get(DataJob, job_id)
        if job is None or job.status != "queued":
            return None  # gone, or already handled by an earlier try
        job.status = "running"
        await db.commit()
        return job


async def _finish(
    deps: Deps, job_id: uuid.UUID, *, error: Exception | None = None, **values: object
) -> None:
    async with deps.sessions() as db:
        job = await db.get(DataJob, job_id)
        if job is None:
            return
        for name, value in values.items():
            setattr(job, name, value)
        job.status = "failed" if error else "done"
        if isinstance(error, AppError):
            job.error_code, job.error_message = error.code, error.message[:500]
        elif error is not None:
            job.error_code = "internal_error"
            job.error_message = "Something went wrong. Nothing was changed; try again."
        job.finished_at = utcnow()
        await db.commit()


async def run_export(deps: Deps, job_id: uuid.UUID) -> None:
    job = await _start(deps, job_id)
    if job is None:
        return
    key = archive_key(job.user_id, job.id, "export")
    try:
        with tempfile.TemporaryDirectory(prefix="revision-os-export-") as tmp:
            path = Path(tmp) / "export.zip"
            async with deps.sessions() as db:
                counts = await build_export(db, deps.storage, deps.config, job.user_id, path)
            await deps.storage.put_file(key, path)
            size = path.stat().st_size
    except Exception as exc:
        logger.exception("export failed", extra={"job_id": str(job_id)})
        await _finish(deps, job_id, error=exc)
        return
    await _finish(deps, job_id, storage_key=key, size_bytes=size, counts=counts)


async def run_restore(deps: Deps, job_id: uuid.UUID, enqueue: Enqueue) -> None:
    job = await _start(deps, job_id)
    if job is None or job.storage_key is None:
        return
    upload = job.storage_key
    try:
        async with deps.storage.local_copy(upload) as archive, deps.sessions() as db:
            restored = await restore_archive(
                db,
                deps.storage,
                deps.config.platform.export,
                deps.config.retrieval.embeddings.model,
                job.user_id,
                archive,
            )
    except Exception as exc:
        if not isinstance(exc, AppError):
            logger.exception("restore failed", extra={"job_id": str(job_id)})
        await _finish(deps, job_id, error=exc, storage_key=None)
        await deps.storage.delete(upload)
        return
    await _finish(deps, job_id, storage_key=None, counts=restored.counts)
    await deps.storage.delete(upload)
    # Search chunks made with a different embedding model are rebuilt.
    for document_id in restored.reindex:
        await enqueue("reindex_document", str(document_id))
