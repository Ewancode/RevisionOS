"""Building an export: one ZIP with everything you have (SPEC 50).

README.md        what is where
manifest.json    format version, schema revision, row counts
data/*.jsonl     every table, one JSON object per row: what restore reads
files/...        your uploaded files, page images and answer photos
csv/*.csv        questions, flashcards, answers, reviews, sessions, ...
markdown/...     materials, lecture text, questions, flashcards, chats
anki/revision-os.apkg   flashcards as Anki decks, one per module
"""

import json
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig
from app.export import readable
from app.export.tables import encode, exported_tables, rows_for_user
from app.storage.base import DATA_FOLDERS, StorageBackend, user_prefix

FORMAT = "revision-os-export"
VERSION = 1
# Files that barely compress (PDFs, PNGs) are stored, saving CPU.
_STORE = (".pdf", ".png", ".jpeg", ".jpg", ".pptx", ".docx", ".xlsx", ".zip")

README = """# Your Revision OS export

Everything you had in Revision OS on {date}.

- `markdown/`: your revision materials, the text of your lecture files,
  questions, flashcards and coding exercises (one folder per module), and
  your conversations with the assistant. Maths is LaTeX between `$` signs.
- `csv/`: tables for a spreadsheet: questions, flashcards, every answer you
  gave, quizzes, flashcard reviews, study sessions, exams, topic progress and
  coding submissions.
- `anki/revision-os.apkg`: your flashcards for Anki (File > Import), one deck
  per module. Importing a later export updates the same cards.
- `files/`: the files you uploaded, their page images and photos of your
  handwritten answers.
- `data/` and `manifest.json`: everything, in the form Revision OS reads back
  (Settings > Your data > Restore, into an empty account).

Items you deleted are only in `data/` (they were in the trash).
"""


async def schema_revision(db: AsyncSession) -> str:
    return str(await db.scalar(text("SELECT version_num FROM alembic_version")))


async def build_export(
    db: AsyncSession,
    storage: StorageBackend,
    config: AppConfig,
    user_id: uuid.UUID,
    out_path: Path,
) -> dict[str, int]:
    """Write the archive to `out_path`; returns rows per table (and files)."""
    counts: dict[str, int] = {}
    now = datetime.now(UTC)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:

        def write(name: str, data: bytes) -> None:
            zf.writestr(name, data)

        for table in exported_tables():
            n = 0
            with zf.open(f"data/{table.name}.jsonl", "w", force_zip64=True) as out:
                result = await db.stream(rows_for_user(table, user_id))
                async for row in result:
                    record = {
                        name: encode(table.c[name], value)
                        for name, value in zip(result.keys(), row, strict=True)
                    }
                    out.write(json.dumps(record, ensure_ascii=False).encode() + b"\n")
                    n += 1
            counts[table.name] = n

        prefix = user_prefix(user_id)
        files = 0
        for key in await storage.list_keys(prefix):
            rest = key.removeprefix(prefix)
            if not rest.startswith(DATA_FOLDERS):
                continue
            info = zipfile.ZipInfo(f"files/{rest}", date_time=now.timetuple()[:6])
            info.compress_type = (
                zipfile.ZIP_STORED if rest.lower().endswith(_STORE) else zipfile.ZIP_DEFLATED
            )
            with zf.open(info, "w", force_zip64=True) as out:
                async for chunk in storage.stream(key):
                    out.write(chunk)
            files += 1
        counts["files"] = files

        ctx = await readable.load_context(db, user_id)
        await readable.write_csvs(db, user_id, ctx, write)
        await readable.write_markdown(db, user_id, ctx, write)
        with tempfile.TemporaryDirectory(prefix="revision-os-anki-") as tmp:
            deck = Path(tmp) / "revision-os.apkg"
            if await readable.anki_package(db, user_id, ctx, deck):
                zf.write(deck, "anki/revision-os.apkg", compress_type=zipfile.ZIP_STORED)

        manifest: dict[str, Any] = {
            "format": FORMAT,
            "version": VERSION,
            "exported_at": now.isoformat(),
            "schema_revision": await schema_revision(db),
            "user_id": str(user_id),
            "embedding_model": config.retrieval.embeddings.model,
            "counts": counts,
        }
        write("manifest.json", json.dumps(manifest, indent=2).encode())
        write("README.md", README.format(date=f"{now:%d %B %Y}").encode())
    return counts
