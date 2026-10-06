"""Write docs/database.md from the SQLAlchemy models, so it can't drift.

Usage: ``python -m scripts.database_doc ../docs/database.md`` (``make db-docs``).
A test fails when the committed file is out of date.
"""

import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import Column, Enum, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

import app.models  # noqa: F401  (registers every table)
from app.db.base import Base
from app.export.tables import EXCLUDED

INTRO = """# Database

PostgreSQL 16 with pgvector. Generated from the models by
`make db-docs` (`backend/scripts/database_doc.py`); do not edit by hand. The
reasoning is in ARCHITECTURE.md section 5 and the ADRs.

Conventions:

- **Every user's data carries `user_id`**, and every query is scoped by it.
  Where a row points at another user-owned row, the foreign key includes
  `user_id` too (`(module_id, user_id) -> modules (id, user_id)`), so the
  database itself refuses a link between two users' data.
- **Ids** are random UUIDs, except a few append-only logs, which are numbered.
- **Times** are `timestamp with time zone`, stored in UTC.
- **Soft delete:** `deleted_at` set means the item is in the trash; the
  scheduler removes it for good after 30 days.
- **Embeddings** are `vector` columns with the model that made them recorded
  alongside, so changing model is a re-index (`make reindex`), not a migration.
- **Exported** marks the tables a data export carries (Settings > Your data;
  `app/export/tables.py`).

"""

GROUPS = {
    "identity": "Accounts and settings",
    "structure": "Years, modules and topics",
    "content": "Uploaded documents",
    "retrieval": "Search",
    "ai": "Claude usage",
    "chat": "The assistant",
    "practice": "Materials, questions, flashcards and quizzes",
    "learning": "Adaptive learning",
    "planner": "Planner and notifications",
    "coding": "Coding practice",
    "exports": "Exports and restores",
}


def _type(column: Column[object]) -> str:
    kind = column.type
    if isinstance(kind, Enum):
        return "enum: " + ", ".join(kind.enums)
    if isinstance(kind, JSONB):
        return "jsonb"
    try:
        return str(kind.compile(dialect=postgresql.dialect())).lower()  # type: ignore[no-untyped-call]
    except Exception:  # types without a generic SQL name
        return type(kind).__name__.lower()


def _references(table: Table, column: Column[object]) -> str:
    targets = sorted(
        f"{fk.column.table.name}.{fk.column.name}"
        for fk in table.foreign_keys
        if fk.parent is column
    )
    return ", ".join(targets)


def render() -> str:
    docs: dict[str, str] = {}
    module_of: dict[str, str] = {}
    for mapper in Base.registry.mappers:
        table = mapper.local_table
        if isinstance(table, Table):
            doc = (mapper.class_.__doc__ or "").strip().split("\n\n")[0]
            docs[table.name] = " ".join(doc.split())
            module_of[table.name] = mapper.class_.__module__.rsplit(".", 1)[-1]
    grouped: dict[str, list[Table]] = defaultdict(list)
    for table in sorted(Base.metadata.tables.values(), key=lambda t: t.name):
        grouped[module_of.get(table.name, "other")].append(table)

    out = [INTRO]
    for module, title in GROUPS.items():
        tables = grouped.pop(module, [])
        if not tables:
            continue
        out.append(f"## {title}\n")
        for table in tables:
            exported = "" if table.name in EXCLUDED else " · exported"
            out.append(f"### `{table.name}`{exported}\n")
            if docs.get(table.name):
                out.append(f"{docs[table.name]}\n")
            out.append("| Column | Type | Null | References |")
            out.append("| --- | --- | --- | --- |")
            for column in table.columns:
                key = " (key)" if column.primary_key else ""
                null = "yes" if column.nullable and not column.primary_key else ""
                out.append(
                    f"| `{column.name}`{key} | {_type(column)} | {null} | "
                    f"{_references(table, column)} |"
                )
            out.append("")
    if grouped:
        raise RuntimeError(f"tables in no group: {sorted(grouped)}; add them to GROUPS")
    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m scripts.database_doc <output.md>", file=sys.stderr)
        return 2
    Path(argv[0]).write_text(render(), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
