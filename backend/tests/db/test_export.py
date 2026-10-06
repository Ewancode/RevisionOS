"""Export and restore (SPEC 50): a full round trip into another account,
the readable formats, and the rules that keep a crafted archive out."""

import csv
import io
import json
import sqlite3
import uuid
import zipfile
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.core.errors import AppError
from app.db.base import Base
from app.export.archive import build_export
from app.export.restore import restore_archive
from app.export.tables import exported_tables, rows_for_user
from app.models import Document, Material, Message, Question, QuestionAttempt, Topic, UserSettings
from app.storage.local import LocalStorage
from tests.export_support import MODEL, PDF, PNG, seed_everything
from tests.support import make_user

CONFIG = get_config()
LIMITS = CONFIG.platform.export


async def export_to(
    db: AsyncSession, storage: LocalStorage, user_id: uuid.UUID, path: Path
) -> Path:
    await build_export(db, storage, CONFIG, user_id, path)
    return path


async def restore(db: AsyncSession, storage: LocalStorage, user_id: uuid.UUID, path: Path) -> Any:
    return await restore_archive(db, storage, LIMITS, MODEL, user_id, path)


async def counts(db: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    out = {}
    for table in exported_tables():
        query = rows_for_user(table, user_id).subquery()
        out[table.name] = int(await db.scalar(select(func.count()).select_from(query)) or 0)
    return out


def rewrite(source: Path, target: Path, change: Any) -> Path:
    """A copy of an archive with `change(name, data) -> data` applied."""
    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(target, "w") as zout:
        for item in zin.infolist():
            zout.writestr(item.filename, change(item.filename, zin.read(item.filename)))
    return target


async def test_every_table_is_covered(db: AsyncSession, storage: LocalStorage) -> None:
    """The fixture fills every exported table, so the round trip below
    covers each one; a new table must be added to tests/export_support.py."""
    user = await make_user(db)
    await seed_everything(db, storage, user)
    empty = [name for name, n in (await counts(db, user.id)).items() if n == 0]
    assert empty == []


async def test_round_trip_into_another_account(
    db: AsyncSession, storage: LocalStorage, tmp_path: Path
) -> None:
    alice = await make_user(db, "alice@example.com")
    ids = await seed_everything(db, storage, alice)
    archive = await export_to(db, storage, alice.id, tmp_path / "export.zip")
    before = await counts(db, alice.id)

    bob = await make_user(db, "bob@example.com")
    restored = await restore(db, storage, bob.id, archive)
    assert restored.reindex == []
    assert await counts(db, bob.id) == before  # every row, every table
    assert await counts(db, alice.id) == before  # and Alice's untouched
    assert restored.counts["files"] == 3

    # New ids everywhere, all pointing at Bob's own rows.
    doc = await db.scalar(select(Document).where(Document.user_id == bob.id))
    assert doc is not None and doc.id != ids["document"]
    assert doc.storage_key == f"users/{bob.id}/documents/{doc.id}/original"
    assert await storage.read_bytes(doc.storage_key) == PDF
    assert await storage.read_bytes(f"users/{bob.id}/documents/{doc.id}/pages/1.png") == PNG
    answer = await db.scalar(select(QuestionAttempt).where(QuestionAttempt.user_id == bob.id))
    assert answer is not None and answer.response_image_key is not None
    assert str(bob.id) in answer.response_image_key
    assert await storage.read_bytes(answer.response_image_key) == PNG

    # Ids inside text and JSON are rewritten too.
    message = await db.scalar(select(Message).where(Message.user_id == bob.id))
    assert message is not None
    assert f"/documents/{doc.id}/pages/1" in message.content
    assert message.citations == [{"document_id": str(doc.id), "page_no": 1}]
    question = await db.scalar(select(Question).where(Question.user_id == bob.id))
    assert question is not None and question.sources[0]["document_id"] == str(doc.id)

    # Relationships survive: the subtopic's parent, the material's version.
    child = await db.scalar(
        select(Topic).where(Topic.user_id == bob.id, Topic.parent_id.is_not(None))
    )
    assert child is not None
    parent = await db.get(Topic, child.parent_id)
    assert parent is not None and parent.user_id == bob.id and parent.title == "Limits"
    material = await db.scalar(select(Material).where(Material.user_id == bob.id))
    assert material is not None and material.current_version_id is not None
    assert material.current_version_id != ids["version"]

    # Settings replaced; vectors exact.
    settings = await db.get(UserSettings, bob.id)
    assert settings is not None
    await db.refresh(settings)  # the session keeps objects across commits
    assert settings.rest_weekdays == [5, 6]
    chunks = Base.metadata.tables["chunks"]
    vector = await db.scalar(select(chunks.c.embedding).where(chunks.c.user_id == bob.id))
    assert vector is not None and list(vector) == [0.5] * len(vector)


async def test_readable_formats(db: AsyncSession, storage: LocalStorage, tmp_path: Path) -> None:
    user = await make_user(db)
    await seed_everything(db, storage, user)
    archive = await export_to(db, storage, user.id, tmp_path / "export.zip")
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        assert {"README.md", "manifest.json", "csv/questions.csv", "csv/answers.csv",
                "anki/revision-os.apkg"} <= names  # fmt: skip
        assert "markdown/MATH101 Calculus I/materials/Limits summary.md" in names
        assert "markdown/MATH101 Calculus I/lectures/L1 limits.pdf.md" in names
        rows = list(csv.DictReader(io.StringIO(zf.read("csv/questions.csv").decode("utf-8-sig"))))
        assert rows[0]["answer"] == "0" and rows[0]["module"] == "MATH101"
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["counts"]["questions"] == 1 and manifest["user_id"] == str(user.id)
        deck = tmp_path / "deck.apkg"
        deck.write_bytes(zf.read("anki/revision-os.apkg"))
    with zipfile.ZipFile(deck) as apkg:
        (tmp_path / "collection.anki2").write_bytes(apkg.read("collection.anki2"))
    with sqlite3.connect(tmp_path / "collection.anki2") as anki:
        (fields,) = anki.execute("SELECT flds FROM notes").fetchone()
    front, back = fields.split("\x1f")
    assert front == "<p>Define a limit</p>"
    assert "\\(L\\)" in back  # MathJax maths, as Anki shows it


async def test_restore_needs_an_empty_account(
    db: AsyncSession, storage: LocalStorage, tmp_path: Path
) -> None:
    user = await make_user(db)
    await seed_everything(db, storage, user)
    archive = await export_to(db, storage, user.id, tmp_path / "export.zip")
    with pytest.raises(AppError) as caught:
        await restore(db, storage, user.id, archive)
    assert caught.value.code == "account_not_empty"


def _foreign_topic(table: str, row: dict[str, Any]) -> dict[str, Any]:
    # A reference to a row not in the archive (perhaps someone else's topic).
    return {**row, "topic_id": str(uuid.uuid4())} if table == "questions" else row


def _other_user(table: str, row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "user_id": str(uuid.uuid4())} if table == "flashcards" else row


def _bad_value(table: str, row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "rating": "high"} if table == "questions" else row


@pytest.mark.parametrize("tamper", [_foreign_topic, _other_user, _bad_value])
async def test_a_tampered_archive_changes_nothing(
    db: AsyncSession, storage: LocalStorage, tmp_path: Path, tamper: Any
) -> None:
    alice = await make_user(db, "alice@example.com")
    await seed_everything(db, storage, alice)
    archive = await export_to(db, storage, alice.id, tmp_path / "export.zip")

    def change(name: str, data: bytes) -> bytes:
        if not name.startswith("data/"):
            return data
        table = name.removeprefix("data/").removesuffix(".jsonl")
        rows = (tamper(table, json.loads(line)) for line in data.splitlines())
        return b"".join(json.dumps(row).encode() + b"\n" for row in rows)

    bad = rewrite(archive, tmp_path / "bad.zip", change)
    bob = (await make_user(db, "bob@example.com")).id  # (the rollback expires the object)
    with pytest.raises(AppError) as caught:
        await restore(db, storage, bob, bad)
    assert caught.value.code == "bad_archive"
    assert sum((await counts(db, bob)).values()) == 1  # only Bob's own settings row
    assert await storage.list_keys(f"users/{bob}/") == []  # copied files removed again


async def test_unsafe_or_oversized_archives_are_refused(
    db: AsyncSession, storage: LocalStorage, tmp_path: Path
) -> None:
    user = await make_user(db, "alice@example.com")
    await seed_everything(db, storage, user)
    archive = await export_to(db, storage, user.id, tmp_path / "export.zip")
    bob = (await make_user(db, "bob@example.com")).id

    async def refused(path: Path) -> str:
        with pytest.raises(AppError) as caught:
            await restore(db, storage, bob, path)
        return caught.value.message

    # A path that climbs out of the archive.
    with zipfile.ZipFile(archive) as zin, zipfile.ZipFile(tmp_path / "climb.zip", "w") as zout:
        for item in zin.infolist():
            zout.writestr(item, zin.read(item.filename))
        zout.writestr("files/../../etc/passwd", b"x")
    assert "unsafe name" in await refused(tmp_path / "climb.zip")

    # A file that is not one Revision OS keeps.
    with zipfile.ZipFile(archive) as zin, zipfile.ZipFile(tmp_path / "odd.zip", "w") as zout:
        for item in zin.infolist():
            zout.writestr(item, zin.read(item.filename))
        zout.writestr(f"files/documents/{uuid.uuid4()}/original", b"x")
    assert "belongs to nothing" in await refused(tmp_path / "odd.zip")

    # A zip bomb: 50 MB of zeros compresses about 1000:1.
    with zipfile.ZipFile(tmp_path / "bomb.zip", "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("manifest.json", b"{}")
        zout.writestr("data/questions.jsonl", b"\0" * 50_000_000)
    assert "expands too much" in await refused(tmp_path / "bomb.zip")

    # Not an export at all, and an export from a newer version.
    with zipfile.ZipFile(tmp_path / "other.zip", "w") as zout:
        zout.writestr("hello.txt", b"hi")
    assert "not a Revision OS export" in await refused(tmp_path / "other.zip")
    newer = rewrite(
        archive,
        tmp_path / "newer.zip",
        lambda name, data: (
            json.dumps({**json.loads(data), "schema_revision": "9999"}).encode()
            if name == "manifest.json"
            else data
        ),
    )
    assert "newer version" in await refused(newer)
    assert sum((await counts(db, bob)).values()) == 1
