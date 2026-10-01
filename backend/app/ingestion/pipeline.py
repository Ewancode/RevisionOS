"""Document processing (ARCHITECTURE.md section 7, "Ingestion stages").

queued -> extracting -> transcribing -> ready (or failed)

Idempotent and resumable: re-running keeps pages that were already
transcribed by Claude or corrected by hand, and only redoes the rest. One
bad page never fails the document; it is flagged for review instead.
"""

import asyncio
import logging
import shutil
import tempfile
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import ClaudeClient
from app.ai.transcription import PageImage, prepare_image, transcribe_page
from app.core.config import AppConfig
from app.core.errors import AppError
from app.ingestion.extract import ExtractedPage, VisionReason, extract, render_pdf_page
from app.ingestion.render import office_to_pdf
from app.ingestion.text import clean_text
from app.ingestion.validation import IMAGE_KINDS, MIME, Kind
from app.models import Document, DocumentPage
from app.storage import StorageBackend

logger = logging.getLogger(__name__)

KIND_BY_MIME = {mime: kind for kind, mime in MIME.items()}
KEEP_METHODS = {"vision", "corrected"}  # never overwritten by a re-run
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

# Progress milestones shown to the user (percent).
EXTRACTED = 40
DONE = 100


@dataclass
class Deps:
    sessions: SessionFactory
    storage: StorageBackend
    claude: ClaudeClient
    config: AppConfig


REVIEW_NOTES = {
    "ai_not_configured": "Not transcribed: Claude is not configured (no API key).",
    "ai_budget_reached": "Not transcribed: the AI budget is used up. Retry when it resets.",
    "ai_unavailable": "Not transcribed: Claude could not be reached. Retry later.",
    "ai_refused": "Not transcribed: Claude declined this page.",
    "ai_truncated": "Not transcribed: the page was too long for one pass.",
    "ai_bad_output": "Not transcribed: Claude returned malformed output.",
    "no_renderer": "Contains equation objects that need LibreOffice to render; check this slide.",
}


async def _set_progress(db: AsyncSession, doc: Document, stage: str, progress: int) -> None:
    doc.stage = stage
    doc.progress = progress
    await db.commit()


def _kind(doc: Document) -> Kind:
    return KIND_BY_MIME[doc.mime]


class _Renderer:
    """Page images for vision, created lazily (LibreOffice is slow)."""

    def __init__(self, doc: Document, source: Path, kind: Kind, config: AppConfig) -> None:
        self.source, self.kind, self.config = source, kind, config
        self._workdir: Path | None = None
        self._pdf: Path | None = None
        self._tried_office = False

    async def image(self, page_no: int) -> PageImage | None:
        ingestion = self.config.platform.ingestion
        if self.kind in IMAGE_KINDS:
            data = await asyncio.to_thread(self.source.read_bytes)
        else:
            pdf = self.source if self.kind is Kind.PDF else await self._office_pdf()
            if pdf is None:
                return None
            data = await asyncio.to_thread(
                render_pdf_page,
                pdf,
                page_no,
                ingestion.vision_render_dpi,
                ingestion.vision_max_long_edge_px,
            )
        return await asyncio.to_thread(prepare_image, data, ingestion.vision_max_long_edge_px)

    async def _office_pdf(self) -> Path | None:
        if not self._tried_office:
            self._tried_office = True
            self._workdir = Path(tempfile.mkdtemp(prefix="revision-os-render-"))
            try:
                self._pdf = await asyncio.to_thread(office_to_pdf, self.source, self._workdir)
            except Exception:
                logger.warning("office to pdf conversion failed", exc_info=True)
                self._pdf = None
        return self._pdf

    def close(self) -> None:
        if self._workdir is not None:
            shutil.rmtree(self._workdir, ignore_errors=True)


async def _save_extracted(
    db: AsyncSession, doc: Document, pages: list[ExtractedPage]
) -> dict[int, DocumentPage]:
    existing = {
        p.page_no: p
        for p in (
            await db.scalars(select(DocumentPage).where(DocumentPage.document_id == doc.id))
        ).all()
    }
    for page in pages:
        row = existing.get(page.page_no)
        if row is not None and row.extraction_method in KEEP_METHODS:
            continue
        if row is None:
            row = DocumentPage(document_id=doc.id, page_no=page.page_no)
            db.add(row)
            existing[page.page_no] = row
        row.markdown = clean_text(page.markdown)
        row.extraction_method = "text"
        row.maths_damage_score = page.damage
        row.needs_review = False
        row.review_note = None
    # Pages beyond the new page count (a re-run of a changed file) go.
    for page_no in [n for n in existing if n > len(pages)]:
        await db.delete(existing.pop(page_no))
    doc.page_count = len(pages)
    await db.commit()
    return existing


async def _transcribe_one(
    deps: Deps,
    db: AsyncSession,
    doc: Document,
    row: DocumentPage,
    reason: VisionReason,
    renderer: _Renderer,
) -> None:
    image = await renderer.image(row.page_no)
    if image is None:
        row.needs_review = True
        row.review_note = REVIEW_NOTES["no_renderer"]
        await db.commit()
        return
    try:
        result = await transcribe_page(
            deps.claude,
            db,
            user_id=doc.user_id,
            document_id=doc.id,
            module_id=doc.module_id,
            image=image,
            page_no=row.page_no,
            filename=doc.original_filename,
            text_hint=row.markdown if reason is VisionReason.MATHS_DAMAGE else "",
        )
    except AppError as exc:
        row.needs_review = True
        row.review_note = REVIEW_NOTES.get(exc.code, f"Not transcribed: {exc.message}")
        if not row.markdown.strip():
            row.extraction_method = "unreadable"
        await db.commit()
        return
    row.markdown = clean_text(result.markdown)
    row.extraction_method = "vision"
    row.needs_review = result.confidence == "low"
    row.review_note = clean_text(result.notes)[:300] or None
    await db.commit()


async def process_document(deps: Deps, document_id: uuid.UUID) -> None:
    async with deps.sessions() as db:
        doc = await db.get(Document, document_id)
        if doc is None or doc.deleted_at is not None:
            return
        doc.status, doc.error_code = "processing", None
        await _set_progress(db, doc, "extracting", 5)
        kind = _kind(doc)
        renderer: _Renderer | None = None
        try:
            source = await deps.storage.local_path(doc.storage_key)
            pages = await asyncio.to_thread(extract, source, kind, deps.config.platform.ingestion)
            rows = await _save_extracted(db, doc, pages)
            await _set_progress(db, doc, "transcribing", EXTRACTED)

            todo = [
                (rows[p.page_no], p.vision_reason)
                for p in pages
                if p.vision_reason is not None
                and rows[p.page_no].extraction_method not in KEEP_METHODS
            ]
            renderer = _Renderer(doc, source, kind, deps.config)
            for done, (row, reason) in enumerate(todo, start=1):
                assert reason is not None  # noqa: S101  # filtered above
                await _transcribe_one(deps, db, doc, row, reason, renderer)
                await _set_progress(
                    db, doc, "transcribing", EXTRACTED + (DONE - EXTRACTED - 1) * done // len(todo)
                )

            doc.status = "ready"
            await _set_progress(db, doc, "ready", DONE)
        except Exception as exc:
            await db.rollback()
            doc = await db.get(Document, document_id)
            if doc is not None:
                doc.status = "failed"
                doc.error_code = exc.code if isinstance(exc, AppError) else "processing_failed"
                await _set_progress(db, doc, "failed", doc.progress)
            logger.exception("document processing failed", extra={"document_id": str(document_id)})
        finally:
            if renderer is not None:
                renderer.close()


async def retranscribe_page(deps: Deps, document_id: uuid.UUID, page_no: int) -> None:
    """Re-run vision on one page on request (replaces text or an earlier
    transcription; a hand correction is replaced only because the user asked)."""
    async with deps.sessions() as db:
        doc = await db.get(Document, document_id)
        row = await db.get(DocumentPage, (document_id, page_no))
        if doc is None or row is None or doc.deleted_at is not None:
            return
        source = await deps.storage.local_path(doc.storage_key)
        renderer = _Renderer(doc, source, _kind(doc), deps.config)
        try:
            await _transcribe_one(deps, db, doc, row, VisionReason.MATHS_DAMAGE, renderer)
        finally:
            renderer.close()
