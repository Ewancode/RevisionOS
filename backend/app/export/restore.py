"""Restoring an export into an account (SPEC 50: never trapped).

The rules:

- **Into an empty account only** (no academic years, so no modules or anything
  under them). Settings, availability, notifications, the plan and weekly
  profiles are replaced; AI usage and conversations are added.
- **Every row gets a new id** and your user id, so an archive can go back
  into the same server, another one, or a second account without clashing.
  Ids inside text and JSON (storage keys, links, citations) are rewritten too.
- **Nothing may point outside the archive:** a reference to a row it does not
  contain stops the restore, so a crafted archive cannot link to someone
  else's data.
- **Files are copied only to keys built here** (the user's folder plus a
  validated relative path); the archive's own names are never used as paths.
- **All or nothing:** one transaction. Files copied before a failure are
  removed again.

Archives from older versions restore: columns are matched by name and new
ones take their defaults. Archives from a newer version are refused.
"""

import json
import re
import shutil
import tempfile
import uuid
import zipfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import Table, Uuid, delete, func, insert, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import String, Text

from app.core.config import ExportConfig
from app.core.errors import AppError
from app.core.settings import BACKEND_ROOT
from app.db.base import Base
from app.export.archive import FORMAT, VERSION, schema_revision
from app.export.tables import (
    REPLACED,
    decode,
    exported_tables,
    generated_key,
    uuid_key,
)
from app.storage.base import DATA_FOLDERS, StorageBackend, StorageKeyError, validate_key

BATCH = 500
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# A large entry compressing better than this is treated as a zip bomb.
_RATIO_FLOOR_BYTES = 1024 * 1024


def bad_archive(message: str) -> AppError:
    return AppError("bad_archive", message, 422)


@dataclass
class Restored:
    counts: dict[str, int]
    # Documents whose search index was built with another embedding model.
    reindex: list[uuid.UUID]


def check_archive(zf: zipfile.ZipFile, limits: ExportConfig) -> dict[str, Any]:
    """Structure and size checks, before anything is read: returns the manifest."""
    entries = zf.infolist()
    if len(entries) > limits.max_restore_entries:
        raise bad_archive("This archive has more files than an export can.")
    total = 0
    for entry in entries:
        name = entry.filename
        if name.startswith(("/", "\\")) or "\\" in name or ".." in name.split("/"):
            raise bad_archive("This archive contains a file with an unsafe name.")
        total += entry.file_size
        if (
            entry.file_size > _RATIO_FLOOR_BYTES
            and entry.file_size > limits.max_restore_compression_ratio * max(entry.compress_size, 1)
        ):
            raise bad_archive("This archive expands too much to be an export.")
    if total > limits.max_restore_uncompressed_megabytes * 1024 * 1024:
        raise bad_archive("This archive is too large once unpacked.")
    try:
        manifest = json.loads(zf.read("manifest.json"))
    except (KeyError, ValueError) as exc:
        raise bad_archive("This is not a Revision OS export (no manifest).") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise bad_archive("This is not a Revision OS export.")
    if manifest.get("version") != VERSION:
        raise bad_archive("This export was made by a different version of Revision OS.")
    try:
        uuid.UUID(str(manifest.get("user_id")))
    except ValueError as exc:
        raise bad_archive("The export's manifest is damaged.") from exc
    return manifest


def known_revisions() -> set[str]:
    script = ScriptDirectory.from_config(AlembicConfig(str(BACKEND_ROOT / "alembic.ini")))
    return {rev.revision for rev in script.walk_revisions()}


def _rows(zf: zipfile.ZipFile, table: Table) -> Iterator[dict[str, Any]]:
    try:
        handle = zf.open(f"data/{table.name}.jsonl")
    except KeyError:
        return  # an older export without this table
    with handle:
        for n, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise bad_archive(f"{table.name} line {n} is damaged.") from exc
            if not isinstance(row, dict):
                raise bad_archive(f"{table.name} line {n} is damaged.")
            yield row


class Remapper:
    """Old ids to new ones; the old user id to yours."""

    def __init__(self, old_user: uuid.UUID, new_user: uuid.UUID) -> None:
        self.ids: dict[uuid.UUID, uuid.UUID] = {old_user: new_user}
        self.text_ids: dict[str, str] = {str(old_user): str(new_user)}

    def add(self, old: uuid.UUID) -> None:
        if old in self.ids:
            raise bad_archive("The export repeats an id.")
        new = uuid.uuid4()
        self.ids[old] = new
        self.text_ids[str(old)] = str(new)

    def text(self, value: str) -> str:
        return _UUID.sub(lambda m: self.text_ids.get(m.group(0), m.group(0)), value)

    def json(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.json(v) for v in value]
        if isinstance(value, dict):
            return {self.text(k): self.json(v) for k, v in value.items()}
        return value


def _convert(
    table: Table, raw: dict[str, Any], ids: Remapper, old_user: uuid.UUID, new_user: uuid.UUID
) -> dict[str, Any]:
    fk_columns = {fk.parent.name for fk in table.foreign_keys}
    own_key = uuid_key(table)
    skip = generated_key(table)
    row: dict[str, Any] = {}
    for column in table.c:
        if column.name not in raw or column is skip or column.computed is not None:
            continue
        try:
            value = decode(column, raw[column.name])
        except (ValueError, TypeError) as exc:
            raise bad_archive(f"{table.name}: {exc}") from exc
        if value is not None and isinstance(column.type, Uuid):
            if column.name == "user_id":
                if value != old_user:
                    raise bad_archive(f"{table.name}: a row belongs to someone else.")
                value = new_user
            elif value in ids.ids:
                value = ids.ids[value]
            elif column is own_key or column.name in fk_columns:
                raise bad_archive(f"{table.name}: a row refers to something not in the export.")
            else:
                value = None  # a loose reference to something since deleted
        elif isinstance(value, str) and isinstance(column.type, String | Text):
            value = ids.text(value)
        elif isinstance(column.type, JSONB):
            value = ids.json(value)
        row[column.name] = value
    if "user_id" in table.c and "user_id" not in row:
        row["user_id"] = new_user
    return row


async def restore_archive(
    db: AsyncSession,
    storage: StorageBackend,
    limits: ExportConfig,
    embedding_model: str,
    user_id: uuid.UUID,
    archive: Path,
) -> Restored:
    """Read `archive` into the (empty) account `user_id`, then commit."""
    years = Base.metadata.tables["academic_years"]
    if await db.scalar(select(func.count()).select_from(years).where(years.c.user_id == user_id)):
        raise AppError(
            "account_not_empty",
            "Restore needs an empty account: this one already has academic years. "
            "Sign in to a new account (make create-user) and restore there.",
            409,
        )
    copied: list[str] = []
    try:
        with zipfile.ZipFile(archive) as zf:
            manifest = check_archive(zf, limits)
            if str(manifest.get("schema_revision")) not in known_revisions():
                raise bad_archive(
                    "This export is from a newer version of Revision OS. Update this one first."
                )
            old_user = uuid.UUID(str(manifest["user_id"]))
            ids = Remapper(old_user, user_id)
            tables = exported_tables()
            for table in tables:
                key = uuid_key(table)
                if key is None:
                    continue
                for raw in _rows(zf, table):
                    try:
                        ids.add(uuid.UUID(str(raw.get(key.name))))
                    except ValueError as exc:
                        raise bad_archive(f"{table.name}: a row has no valid id.") from exc

            for name in REPLACED:
                table = Base.metadata.tables[name]
                await db.execute(delete(table).where(table.c.user_id == user_id))

            counts: dict[str, int] = {}
            stale_models: set[uuid.UUID] = set()
            for table in tables:
                n, batch = 0, []
                converted = (_convert(table, r, ids, old_user, user_id) for r in _rows(zf, table))
                for row in _parents_first(table, converted):
                    if table.name == "chunks" and row.get("embedding_model") != embedding_model:
                        stale_models.add(row["document_id"])
                    batch.append(row)
                    if len(batch) == BATCH:
                        await db.execute(insert(table), batch)
                        n, batch = n + len(batch), []
                if batch:
                    await db.execute(insert(table), batch)
                    n += len(batch)
                counts[table.name] = n

            prefix = f"users/{user_id}/"
            for entry in zf.infolist():
                if not entry.filename.startswith("files/") or entry.is_dir():
                    continue
                rest = entry.filename.removeprefix("files/")
                if not rest.startswith(DATA_FOLDERS):
                    continue
                if any(m not in ids.text_ids for m in _UUID.findall(rest)):
                    raise bad_archive("A file in the export belongs to nothing in it.")
                try:
                    target = validate_key(prefix + ids.text(rest))
                except StorageKeyError as exc:
                    raise bad_archive("The export has a file Revision OS does not keep.") from exc
                with zf.open(entry) as source, _spooled(source) as path:
                    await storage.put_file(target, path)
                copied.append(target)
            counts["files"] = len(copied)
        await db.commit()
    except BaseException:
        await db.rollback()
        for target in copied:
            await storage.delete(target)
        raise
    return Restored(counts, sorted(stale_models))


def _parents_first(table: Table, rows: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    """Rows of a table that refers to itself (topics have parent topics),
    ordered so each parent is inserted before its children."""
    key = uuid_key(table)
    if key is None:
        return rows
    own = [
        fk.parent.name
        for fk in table.foreign_keys
        if fk.column.table is table and fk.column.name == key.name
    ]
    if not own:
        return rows
    pending = list(rows)
    done: set[Any] = set()
    ordered: list[dict[str, Any]] = []
    while pending:
        ready = [r for r in pending if all(r.get(c) in done or r.get(c) is None for c in own)]
        if not ready:
            raise bad_archive(f"{table.name}: rows refer to each other in a loop.")
        ordered.extend(ready)
        done.update(r[key.name] for r in ready)
        pending = [r for r in pending if r[key.name] not in done]
    return ordered


@contextmanager
def _spooled(source: IO[bytes]) -> Iterator[Path]:
    """One archive entry as a temporary file (storage takes a path)."""
    with tempfile.TemporaryDirectory(prefix="revision-os-restore-") as tmp:
        path = Path(tmp) / "file"
        with path.open("wb") as out:
            shutil.copyfileobj(source, out, 1024 * 1024)
        yield path


__all__ = ["Restored", "check_archive", "restore_archive", "schema_revision"]
