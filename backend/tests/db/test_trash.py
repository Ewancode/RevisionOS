"""Emptying the trash: after 30 days, deleted items go for good, files too."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, Flashcard, Material, Module, User
from app.storage.base import document_key
from app.storage.local import LocalStorage
from app.trash import purge
from tests.learning_support import make_module
from tests.support import make_user

pytestmark = pytest.mark.db

NOW = datetime(2026, 10, 5, 9, tzinfo=UTC)
OLD = NOW - timedelta(days=31)
RECENT = NOW - timedelta(days=10)


async def document(
    db: AsyncSession, storage: LocalStorage, user: User, module: Module, deleted: datetime | None
) -> Document:
    doc = Document(
        id=uuid.uuid4(), user_id=user.id, module_id=module.id, original_filename="w.pdf",
        storage_key="", mime="application/pdf", size_bytes=3, sha256=uuid.uuid4().bytes * 2,
        source_tier="university", material_kind="lecture", deleted_at=deleted,
    )  # fmt: skip
    doc.storage_key = document_key(user.id, doc.id)
    await storage.put_bytes(doc.storage_key, b"pdf")
    db.add(doc)
    await db.flush()
    return doc


async def test_old_trash_is_emptied_with_its_files(db: AsyncSession, storage: LocalStorage) -> None:
    user = await make_user(db)
    live, _, year = await make_module(db, user, "MATH101", [])
    gone, _, _ = await make_module(db, user, "OLD100", [], year)
    gone.deleted_at = OLD
    old_doc = await document(db, storage, user, live, OLD)
    kept_doc = await document(db, storage, user, live, None)
    recent_doc = await document(db, storage, user, live, RECENT)
    inside_gone = await document(db, storage, user, gone, None)
    db.add_all(
        [
            Flashcard(id=uuid.uuid4(), user_id=user.id, module_id=live.id, front_md="f",
                      back_md="b", origin="user", deleted_at=NOW - timedelta(days=40)),
            Material(id=uuid.uuid4(), user_id=user.id, module_id=live.id, title="Recent",
                     kind="notes", origin="user", deleted_at=RECENT),
        ]
    )  # fmt: skip
    await db.commit()

    counts = await purge(db, storage, 30, NOW)
    assert counts == {"documents": 2, "flashcards": 1, "modules": 1}
    left = set((await db.scalars(select(Document.id))).all())
    assert left == {kept_doc.id, recent_doc.id}
    assert await db.scalar(select(Material.title)) == "Recent"
    assert (await db.scalars(select(Module.code))).all() == ["MATH101"]
    for doc, exists in (
        (old_doc, False),
        (inside_gone, False),
        (kept_doc, True),
        (recent_doc, True),
    ):
        assert await storage.exists(doc.storage_key) is exists
    # Nothing more to do the next day.
    assert await purge(db, storage, 30, NOW + timedelta(hours=1)) == {}
