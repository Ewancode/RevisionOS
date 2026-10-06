"""Your data: export everything as a ZIP, or restore one (SPEC 50)."""

import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import Client, Config, CurrentUser, DbSession, rate_limited
from app.api.uploads import receive_to_file
from app.core.config import AppConfig
from app.models import DataJob
from app.schemas.exports import DataJobOut
from app.services.exports import ExportService

router = APIRouter(tags=["export"])


def _service(
    request: Request, db: DbSession, user: CurrentUser, client: Client, config: Config
) -> ExportService:
    return ExportService(
        db,
        user.id,
        client,
        storage=request.app.state.storage,
        jobs=request.app.state.jobs,
        config=config,
    )


Exports = Annotated[ExportService, Depends(_service)]


def _out(job: DataJob, config: AppConfig) -> DataJobOut:
    out = DataJobOut.model_validate(job, from_attributes=True)
    if job.kind == "export" and job.status == "done" and job.storage_key:
        out.expires_at = job.created_at + timedelta(days=config.platform.export.keep_days)
    return out


@router.post(
    "/export",
    response_model=DataJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[rate_limited("exports")],
)
async def start_export(exports: Exports, config: Config) -> DataJobOut:
    """Build a ZIP of everything in the background; poll GET /export/{id}."""
    return _out(await exports.start_export(), config)


@router.get("/export", response_model=list[DataJobOut])
async def list_exports(exports: Exports, config: Config) -> list[DataJobOut]:
    """Your ten most recent exports and restores."""
    return [_out(job, config) for job in await exports.list()]


@router.get("/export/{job_id}", response_model=DataJobOut)
async def get_export(job_id: uuid.UUID, exports: Exports, config: Config) -> DataJobOut:
    return _out(await exports.get(job_id), config)


@router.get("/export/{job_id}/file", response_class=StreamingResponse)
async def download_export(
    job_id: uuid.UUID, request: Request, exports: Exports
) -> StreamingResponse:
    key, size, filename = await exports.download(job_id)
    return StreamingResponse(
        request.app.state.storage.stream(key),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(size),
        },
    )


@router.post(
    "/export/restore",
    response_model=DataJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[rate_limited("exports")],
)
async def restore_export(request: Request, exports: Exports, config: Config) -> DataJobOut:
    """Upload an export (the raw ZIP as the request body) to restore it into
    this account, which must be empty. Runs in the background."""
    limit = config.platform.export.max_restore_megabytes * 1024 * 1024
    with tempfile.TemporaryDirectory(prefix="revision-os-restore-") as tmp:
        path = Path(tmp) / "archive.zip"
        await receive_to_file(request, limit, path)
        job = await exports.start_restore(path)
    return _out(job, config)
