"""Exporting your data and restoring it (SPEC 50)."""

import asyncio
import uuid
import zipfile
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import AppConfig
from app.core.errors import AppError
from app.export.restore import check_archive
from app.models import AcademicYear, DataJob
from app.services.common import ClientInfo, ScopedService, not_found
from app.storage.base import StorageBackend, archive_key
from app.workers.queue import JobQueue

ACTIVE = ("queued", "running")


class ExportService(ScopedService):
    def __init__(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        client: ClientInfo,
        *,
        storage: StorageBackend,
        jobs: JobQueue,
        config: AppConfig,
    ) -> None:
        super().__init__(db, user_id, client)
        self.storage = storage
        self.jobs = jobs
        self.config = config

    async def list(self) -> Sequence[DataJob]:
        return (
            await self.db.scalars(
                select(DataJob)
                .where(DataJob.user_id == self.user_id)
                .order_by(DataJob.created_at.desc())
                .limit(10)
            )
        ).all()

    async def get(self, job_id: uuid.UUID) -> DataJob:
        job = await self.db.scalar(
            select(DataJob).where(DataJob.id == job_id, DataJob.user_id == self.user_id)
        )
        if job is None:
            raise not_found("export")
        return job

    async def _one_at_a_time(self) -> None:
        busy = await self.db.scalar(
            select(func.count())
            .select_from(DataJob)
            .where(DataJob.user_id == self.user_id, DataJob.status.in_(ACTIVE))
        )
        if busy:
            raise AppError(
                "export_running",
                "An export or restore is already running. Wait for it to finish.",
                409,
            )

    async def start_export(self) -> DataJob:
        await self._one_at_a_time()
        job = DataJob(id=uuid.uuid4(), user_id=self.user_id, kind="export")
        self.db.add(job)
        self.audit.record(
            "data.export",
            user_id=self.user_id,
            target_type="data_job",
            target_id=job.id,
            ip=self.client.ip,
            user_agent=self.client.user_agent,
        )
        await self.db.commit()
        await self.jobs.enqueue("run_export", str(job.id), job_id=f"export:{job.id}")
        return job

    async def download(self, job_id: uuid.UUID) -> tuple[str, int, str]:
        """The finished export's storage key, size and a file name."""
        job = await self.get(job_id)
        if job.kind != "export" or job.status != "done":
            raise AppError("export_not_ready", "That export is not ready.", 409)
        if job.storage_key is None or job.size_bytes is None:
            raise AppError(
                "export_expired",
                "That export has expired. Start a new one.",
                410,
            )
        return job.storage_key, job.size_bytes, f"revision-os-{job.created_at:%Y-%m-%d}.zip"

    async def start_restore(self, upload: Path) -> DataJob:
        """Check an uploaded archive, store it and queue the restore."""
        await self._one_at_a_time()
        if await self.db.scalar(
            select(func.count())
            .select_from(AcademicYear)
            .where(AcademicYear.user_id == self.user_id)
        ):
            raise AppError(
                "account_not_empty",
                "Restore needs an empty account: this one already has academic years. "
                "Sign in to a new account (make create-user) and restore there.",
                409,
            )

        def check() -> int:
            try:
                with zipfile.ZipFile(upload) as zf:
                    check_archive(zf, self.config.platform.export)
            except zipfile.BadZipFile as exc:
                raise AppError("bad_archive", "That file is not a ZIP archive.", 422) from exc
            return upload.stat().st_size

        size = await asyncio.to_thread(check)
        job = DataJob(id=uuid.uuid4(), user_id=self.user_id, kind="restore", status="queued")
        job.storage_key = archive_key(self.user_id, job.id, "restore")
        job.size_bytes = size
        await self.storage.put_file(job.storage_key, upload)
        self.db.add(job)
        self.audit.record(
            "data.restore",
            user_id=self.user_id,
            target_type="data_job",
            target_id=job.id,
            ip=self.client.ip,
            user_agent=self.client.user_agent,
        )
        await self.db.commit()
        await self.jobs.enqueue("run_restore", str(job.id), job_id=f"restore:{job.id}")
        return job


async def expire_exports(db: AsyncSession, storage: StorageBackend, keep_days: int) -> int:
    """Delete export archives older than `keep_days` (the jobs stay, as history)."""
    cutoff = utcnow() - timedelta(days=keep_days)
    jobs = (
        await db.scalars(
            select(DataJob).where(
                DataJob.kind == "export",
                DataJob.storage_key.is_not(None),
                DataJob.created_at < cutoff,
            )
        )
    ).all()
    # Rows first, then files (as the trash does): never a link to a missing file.
    keys = [job.storage_key for job in jobs if job.storage_key]
    for job in jobs:
        job.storage_key = None
        job.size_bytes = None
    await db.commit()
    for key in keys:
        await storage.delete(key)
    return len(keys)
