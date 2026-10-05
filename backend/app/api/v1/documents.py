"""Document upload, status, pages and previews."""

import asyncio
import tempfile
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.api.deps import Client, Config, CurrentUser, DbSession, rate_limited
from app.api.uploads import receive_to_file
from app.schemas.documents import (
    DocumentOut,
    DocumentProgress,
    DocumentUpdate,
    MaterialKind,
    PageCorrection,
    PageOut,
    SourceTier,
)
from app.services.documents import DocumentService

router = APIRouter(tags=["documents"])
CHUNK = 1024 * 1024
TERMINAL = {"ready", "failed"}


def _service(
    request: Request, db: DbSession, user: CurrentUser, client: Client, config: Config
) -> DocumentService:
    return DocumentService(
        db,
        user.id,
        client,
        storage=request.app.state.storage,
        jobs=request.app.state.jobs,
        config=config,
    )


Documents = Annotated[DocumentService, Depends(_service)]


@router.post(
    "/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[rate_limited("uploads")],
)
async def upload_document(
    request: Request,
    documents: Documents,
    config: Config,
    filename: Annotated[str, Query(min_length=1, max_length=500)],
    module_id: uuid.UUID,
    source_tier: SourceTier,
    material_kind: MaterialKind,
    topic_id: uuid.UUID | None = None,
    week: Annotated[int | None, Query(ge=0, le=60)] = None,
) -> DocumentOut:
    """Upload a file as the raw request body (any Content-Type); metadata goes
    in the query string. Processing continues in the background: follow it
    with GET /documents/{id}/events."""
    with tempfile.TemporaryDirectory(prefix="revision-os-upload-") as tmp:
        path = Path(tmp) / "upload"
        await receive_to_file(request, config.platform.uploads.largest_upload_bytes, path)
        doc = await documents.upload(
            temp_path=path,
            filename=filename,
            module_id=module_id,
            topic_id=topic_id,
            source_tier=source_tier,
            material_kind=material_kind,
            week=week,
        )
    return DocumentOut.model_validate(doc)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    documents: Documents, module_id: uuid.UUID | None = None
) -> list[DocumentOut]:
    return [DocumentOut.model_validate(d) for d in await documents.list(module_id)]


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(document_id: uuid.UUID, documents: Documents) -> DocumentOut:
    return DocumentOut.model_validate(await documents.get(document_id))


@router.patch("/documents/{document_id}", response_model=DocumentOut)
async def update_document(
    document_id: uuid.UUID, body: DocumentUpdate, documents: Documents
) -> DocumentOut:
    return DocumentOut.model_validate(await documents.update(document_id, body))


@router.post(
    "/documents/{document_id}/reprocess",
    response_model=DocumentOut,
    dependencies=[rate_limited("ai")],
)
async def reprocess_document(document_id: uuid.UUID, documents: Documents) -> DocumentOut:
    return DocumentOut.model_validate(await documents.reprocess(document_id))


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: uuid.UUID, documents: Documents) -> None:
    """Moves the document to the trash."""
    await documents.delete(document_id)


@router.post("/documents/{document_id}/restore", response_model=DocumentOut)
async def restore_document(
    document_id: uuid.UUID, documents: Documents, config: Config
) -> DocumentOut:
    retention = timedelta(days=config.platform.trash.retention_days)
    return DocumentOut.model_validate(await documents.restore(document_id, retention))


@router.get(
    "/documents/{document_id}/events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def document_events(
    document_id: uuid.UUID, request: Request, documents: Documents, db: DbSession, config: Config
) -> StreamingResponse:
    """Server-sent events with processing progress until ready or failed."""
    doc = await documents.get(document_id)
    interval = config.platform.ingestion.progress_poll_seconds

    async def events() -> AsyncIterator[str]:
        last: str | None = None
        while True:
            await db.refresh(doc)
            payload = DocumentProgress.model_validate(doc).model_dump_json()
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if doc.status in TERMINAL or await request.is_disconnected():
                return
            # Close the transaction between polls so we see the worker's commits.
            await db.commit()
            await asyncio.sleep(interval)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@router.get("/documents/{document_id}/file", response_class=StreamingResponse)
async def download_document(
    document_id: uuid.UUID, request: Request, documents: Documents
) -> StreamingResponse:
    """The original file, always as a download (never rendered inline by the API origin)."""
    doc = await documents.get(document_id)
    disposition = f"attachment; filename*=UTF-8''{quote(doc.original_filename)}"
    return StreamingResponse(
        request.app.state.storage.stream(doc.storage_key),
        media_type=doc.mime,
        headers={"Content-Disposition": disposition, "Content-Length": str(doc.size_bytes)},
    )


@router.get("/documents/{document_id}/pages", response_model=list[PageOut])
async def list_pages(document_id: uuid.UUID, documents: Documents) -> list[PageOut]:
    return [PageOut.model_validate(p) for p in await documents.pages(document_id)]


@router.put("/documents/{document_id}/pages/{page_no}", response_model=PageOut)
async def correct_page(
    document_id: uuid.UUID, page_no: int, body: PageCorrection, documents: Documents
) -> PageOut:
    """Replace a page's text with a hand correction (kept on reprocessing)."""
    return PageOut.model_validate(await documents.correct_page(document_id, page_no, body.markdown))


@router.post(
    "/documents/{document_id}/pages/{page_no}/retranscribe",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[rate_limited("ai")],
)
async def retranscribe_page(
    document_id: uuid.UUID, page_no: int, documents: Documents
) -> dict[str, str]:
    await documents.retranscribe(document_id, page_no)
    return {"status": "queued"}


@router.get(
    "/documents/{document_id}/pages/{page_no}/preview",
    response_class=Response,
    responses={200: {"content": {"image/png": {}, "image/jpeg": {}}}},
)
async def page_preview(document_id: uuid.UUID, page_no: int, documents: Documents) -> Response:
    data, media_type = await documents.preview(document_id, page_no)
    return Response(
        content=data, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"}
    )
