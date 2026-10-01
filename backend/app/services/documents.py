"""Uploading, listing, correcting and deleting documents."""

import asyncio
import uuid
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import AppConfig
from app.core.errors import AppError
from app.ingestion.extract import render_pdf_page
from app.ingestion.filenames import extension, sanitise_filename
from app.ingestion.pipeline import KIND_BY_MIME
from app.ingestion.validation import IMAGE_KINDS, Kind, validate_upload
from app.models import Document, DocumentPage
from app.repositories.structure import ModuleRepository, TopicRepository
from app.schemas.documents import DocumentUpdate, MaterialKind, SourceTier
from app.services.common import ClientInfo, ScopedService, not_found
from app.storage import StorageBackend, document_key, page_image_key
from app.storage.base import document_prefix
from app.workers.queue import JobQueue

DUPLICATE_CONSTRAINT = "uq_documents_user_sha256_live"


def _duplicate(existing: Document) -> AppError:
    return AppError(
        "duplicate_upload",
        f"You already uploaded this file as “{existing.original_filename}”.",
        409,
        details={"document_id": str(existing.id)},
    )


class DocumentService(ScopedService):
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

    # --- lookups -------------------------------------------------------------

    def _live(self) -> Select[Document]:
        return select(Document).where(
            Document.user_id == self.user_id, Document.deleted_at.is_(None)
        )

    async def get(self, document_id: uuid.UUID) -> Document:
        doc = await self.db.scalar(self._live().where(Document.id == document_id))
        if doc is None:
            raise not_found("document")
        return doc

    async def list(self, module_id: uuid.UUID | None) -> Sequence[Document]:
        stmt = self._live().order_by(Document.created_at.desc())
        if module_id is not None:
            stmt = stmt.where(Document.module_id == module_id)
        return (await self.db.scalars(stmt)).all()

    async def _check_placement(self, module_id: uuid.UUID, topic_id: uuid.UUID | None) -> None:
        if await ModuleRepository(self.db, self.user_id).get(module_id) is None:
            raise not_found("module")
        if topic_id is not None:
            topic = await TopicRepository(self.db, self.user_id).get(topic_id)
            if topic is None or topic.module_id != module_id:
                raise not_found("topic")

    async def _existing_copy(self, sha256: bytes) -> Document | None:
        return await self.db.scalar(self._live().where(Document.sha256 == sha256))

    # --- upload --------------------------------------------------------------

    async def upload(
        self,
        *,
        temp_path: Path,
        filename: str,
        module_id: uuid.UUID,
        topic_id: uuid.UUID | None,
        source_tier: SourceTier,
        material_kind: MaterialKind,
        week: int | None,
    ) -> Document:
        await self._check_placement(module_id, topic_id)
        name = sanitise_filename(filename)
        validated = await asyncio.to_thread(
            validate_upload, temp_path, extension(name), self.config.platform.uploads
        )
        existing = await self._existing_copy(validated.sha256)
        if existing is not None:
            raise _duplicate(existing)

        doc_id = uuid.uuid4()
        key = document_key(self.user_id, doc_id)
        await self.storage.put_file(key, temp_path)
        doc = Document(
            id=doc_id,
            user_id=self.user_id,
            module_id=module_id,
            topic_id=topic_id,
            original_filename=name,
            storage_key=key,
            mime=validated.mime,
            size_bytes=validated.size_bytes,
            sha256=validated.sha256,
            source_tier=source_tier,
            material_kind=material_kind,
            week=week,
            page_count=validated.page_count,
        )
        self.db.add(doc)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            # A simultaneous upload of the same file won the race.
            await self.db.rollback()
            await self.storage.delete_prefix(document_prefix(self.user_id, doc_id))
            existing = await self._existing_copy(validated.sha256)
            if existing is not None:
                raise _duplicate(existing) from exc
            raise
        await self.jobs.enqueue("process_document", str(doc_id), job_id=f"process:{doc_id}")
        return doc

    # --- changes -------------------------------------------------------------

    async def update(self, document_id: uuid.UUID, body: DocumentUpdate) -> Document:
        doc = await self.get(document_id)
        changes = body.changes()
        if "topic_id" in changes:
            await self._check_placement(doc.module_id, body.topic_id)
        for field, value in changes.items():
            setattr(doc, field, value)
        await self.db.commit()
        return doc

    async def reprocess(self, document_id: uuid.UUID) -> Document:
        doc = await self.get(document_id)
        if doc.status in ("queued", "processing"):
            raise AppError("already_processing", "This document is already being processed.", 409)
        doc.status, doc.stage, doc.progress, doc.error_code = "queued", "queued", 0, None
        await self.db.commit()
        await self.jobs.enqueue(
            "process_document", str(doc.id), job_id=f"process:{doc.id}:{utcnow().timestamp()}"
        )
        return doc

    async def delete(self, document_id: uuid.UUID) -> None:
        doc = await self.get(document_id)
        doc.deleted_at = utcnow()
        self._record("document_deleted", "document", document_id, filename=doc.original_filename)
        await self.db.commit()

    async def restore(self, document_id: uuid.UUID, since: timedelta) -> Document:
        doc = await self.db.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.user_id == self.user_id,
                Document.deleted_at >= utcnow() - since,
            )
        )
        if doc is None:
            raise not_found("document")
        if await ModuleRepository(self.db, self.user_id).get(doc.module_id) is None:
            raise AppError(
                "module_deleted", "Restore the module first; this document belongs to it.", 409
            )
        existing = await self._existing_copy(doc.sha256)
        if existing is not None:
            raise _duplicate(existing)
        doc.deleted_at = None
        self._record("document_restored", "document", document_id, filename=doc.original_filename)
        await self.db.commit()
        return doc

    async def list_deleted(self, since: timedelta) -> Sequence[Document]:
        stmt = (
            select(Document)
            .where(Document.user_id == self.user_id, Document.deleted_at >= utcnow() - since)
            .order_by(Document.deleted_at.desc())
        )
        return (await self.db.scalars(stmt)).all()

    # --- pages ---------------------------------------------------------------

    async def pages(self, document_id: uuid.UUID) -> Sequence[DocumentPage]:
        await self.get(document_id)
        stmt = (
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_no)
        )
        return (await self.db.scalars(stmt)).all()

    async def _page(self, document_id: uuid.UUID, page_no: int) -> tuple[Document, DocumentPage]:
        doc = await self.get(document_id)
        page = await self.db.get(DocumentPage, (document_id, page_no))
        if page is None:
            raise not_found("page")
        return doc, page

    async def correct_page(
        self, document_id: uuid.UUID, page_no: int, markdown: str
    ) -> DocumentPage:
        _, page = await self._page(document_id, page_no)
        page.markdown = markdown
        page.extraction_method = "corrected"
        page.needs_review = False
        page.review_note = None
        await self.db.commit()
        return page

    async def retranscribe(self, document_id: uuid.UUID, page_no: int) -> None:
        doc, _ = await self._page(document_id, page_no)
        if KIND_BY_MIME[doc.mime] not in (IMAGE_KINDS | {Kind.PDF, Kind.PPTX}):
            raise AppError(
                "not_transcribable", "Only PDF, slide and image pages can be transcribed.", 422
            )
        await self.jobs.enqueue(
            "retranscribe_page", str(doc.id), page_no, job_id=f"retranscribe:{doc.id}:{page_no}"
        )

    async def preview(self, document_id: uuid.UUID, page_no: int) -> tuple[bytes, str]:
        """An image of the page, to show beside its transcription."""
        doc, _ = await self._page(document_id, page_no)
        kind = KIND_BY_MIME[doc.mime]
        if kind in IMAGE_KINDS:
            return await self.storage.read_bytes(doc.storage_key), doc.mime
        if kind is not Kind.PDF:
            raise AppError(
                "preview_unavailable", "Page images are available for PDFs and images.", 404
            )
        key = page_image_key(self.user_id, doc.id, page_no)
        if not await self.storage.exists(key):
            source = await self.storage.local_path(doc.storage_key)
            png = await asyncio.to_thread(
                render_pdf_page, source, page_no, self.config.platform.ingestion.preview_dpi
            )
            await self.storage.put_bytes(key, png)
            return png, "image/png"
        return await self.storage.read_bytes(key), "image/png"
