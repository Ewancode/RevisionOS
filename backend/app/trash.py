"""Emptying the trash (SPEC 17: deleted items are kept for 30 days).

Run daily by the scheduler. Anything deleted longer ago than
platform.yaml `trash.retention_days` is removed for good: the row (child
rows go with it, by the foreign keys' ON DELETE CASCADE) and, for uploaded
documents, the stored file and page images. Documents inside a purged
module go too, even if they were not deleted themselves.

Rows are deleted and committed first, then files, so the app never shows an
item whose file has gone. A file that fails to delete is logged and left as
an orphan, never the other way round.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CodingExercise, Document, Flashcard, Material, Module, Topic
from app.storage.base import StorageBackend, document_prefix

logger = logging.getLogger(__name__)


async def purge(
    db: AsyncSession, storage: StorageBackend, retention_days: int, now: datetime
) -> dict[str, int]:
    cutoff = now - timedelta(days=retention_days)
    gone_modules = select(Module.id).where(Module.deleted_at < cutoff)
    documents = (
        await db.execute(
            select(Document.user_id, Document.id).where(
                or_(Document.deleted_at < cutoff, Document.module_id.in_(gone_modules))
            )
        )
    ).all()
    counts: dict[str, int] = {}
    if documents:
        result = await db.execute(
            delete(Document).where(Document.id.in_([d for _, d in documents]))
        )
        counts["documents"] = result.rowcount  # type: ignore[attr-defined]
    for name, model in (
        ("coding_exercises", CodingExercise),
        ("flashcards", Flashcard),
        ("materials", Material),
        ("topics", Topic),
        ("modules", Module),
    ):
        result = await db.execute(delete(model).where(model.deleted_at < cutoff))
        if result.rowcount:  # type: ignore[attr-defined]
            counts[name] = result.rowcount  # type: ignore[attr-defined]
    await db.commit()

    for user_id, document_id in documents:
        try:
            await storage.delete_prefix(document_prefix(user_id, document_id))
        except Exception:
            logger.exception("could not delete a purged document's files")
    if counts:
        logger.info("emptied the trash", extra={"purged": counts})
    return counts
