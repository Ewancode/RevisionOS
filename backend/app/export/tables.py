"""Which tables an export carries, and how each value is written and read
back, driven by the SQLAlchemy metadata so a new table or column is
exported without anyone remembering to add it (a test checks the lists).

Every value is encoded by its column's type, so restore can rebuild it exactly:
UUIDs and dates as strings, bytes as hex, vectors as base64 float32.
"""

import base64
import uuid
from datetime import date, datetime
from typing import Any

import numpy as np
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    Integer,
    LargeBinary,
    Select,
    SmallInteger,
    String,
    Table,
    Text,
    Uuid,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR

import app.models  # noqa: F401  (registers every table)
from app.db.base import Base

# Never exported: who you are and how you sign in belong to the account you
# restore into, devices are tied to a browser, the audit log is the server's
# record, and a deletion awaiting your confirmation would be stale.
EXCLUDED = frozenset(
    {"users", "auth_sessions", "audit_log", "push_subscriptions", "data_jobs", "pending_actions"}
)
# Tables without a user_id column, and the parent that scopes them.
SCOPED_BY_PARENT = {
    "document_pages": ("document_id", "documents"),
    "exam_topics": ("exam_id", "exams"),
}
# Restoring replaces these (settings and things the app makes by itself);
# everything else must be absent from the account first (see restore.py).
REPLACED = (
    "user_settings",
    "availability_rules",
    "availability_overrides",
    "notifications",
    "revision_plans",
    "learning_profile_snapshots",
)


def exported_tables() -> list[Table]:
    """Every exported table, parents before children."""
    return [t for t in Base.metadata.sorted_tables if t.name not in EXCLUDED]


def rows_for_user(table: Table, user_id: uuid.UUID) -> Select[Any]:
    columns = [c for c in table.c if not _skipped(c)]
    if table.name in SCOPED_BY_PARENT:
        fk, parent_name = SCOPED_BY_PARENT[table.name]
        parent = Base.metadata.tables[parent_name]
        owned = select(parent.c.id).where(parent.c.user_id == user_id)
        query = select(*columns).where(table.c[fk].in_(owned))
    else:
        query = select(*columns).where(table.c.user_id == user_id)
    return query.order_by(*table.primary_key.columns)


def _skipped(column: Column[Any]) -> bool:
    """Computed columns (the keyword index) are rebuilt by the database."""
    return column.computed is not None or isinstance(column.type, TSVECTOR)


def generated_key(table: Table) -> Column[Any] | None:
    """An integer primary key the database numbers: restore leaves it out
    (nothing refers to one) so the new rows get fresh numbers."""
    keys = list(table.primary_key.columns)
    if len(keys) == 1 and isinstance(keys[0].type, Integer | BigInteger):
        return keys[0]
    return None


def uuid_key(table: Table) -> Column[Any] | None:
    """A single UUID primary key: restore gives each row a new one. (A table
    keyed by user_id alone, like user_settings, gets the restoring user's.)"""
    keys = list(table.primary_key.columns)
    if len(keys) == 1 and isinstance(keys[0].type, Uuid) and keys[0].name != "user_id":
        return keys[0]
    return None


def encode(column: Column[Any], value: Any) -> Any:
    if value is None:
        return None
    kind = column.type
    if isinstance(kind, Vector):
        return base64.b64encode(np.asarray(value, dtype="<f4").tobytes()).decode()
    if isinstance(kind, Uuid):
        return str(value)
    if isinstance(kind, DateTime | Date):
        return value.isoformat()
    if isinstance(kind, LargeBinary):
        return bytes(value).hex()
    if isinstance(kind, ARRAY):
        return list(value)
    return value  # str, int, float, bool, enum labels and JSON as they are


def decode(column: Column[Any], value: Any) -> Any:
    """The reverse of `encode`, checking each value has its column's type.
    Raises ValueError (or TypeError) on anything else."""
    if value is None:
        return None
    kind = column.type
    if isinstance(kind, Vector):
        vector = np.frombuffer(base64.b64decode(_text(value), validate=True), dtype="<f4")
        if kind.dim is not None and vector.shape != (kind.dim,):
            raise ValueError(f"{column.name}: a vector of the wrong size")
        return vector.tolist()
    if isinstance(kind, Uuid):
        return uuid.UUID(_text(value))
    if isinstance(kind, DateTime):
        parsed = datetime.fromisoformat(_text(value))
        if parsed.tzinfo is None:
            raise ValueError(f"{column.name}: a time without a time zone")
        return parsed
    if isinstance(kind, Date):
        return date.fromisoformat(_text(value))
    if isinstance(kind, LargeBinary):
        return bytes.fromhex(_text(value))
    if isinstance(kind, Enum):
        if value not in kind.enums:
            raise ValueError(f"{column.name}: unknown value {value!r}")
        return value
    if isinstance(kind, String | Text):
        text = _text(value)
        if kind.length is not None and len(text) > kind.length:
            raise ValueError(f"{column.name}: longer than {kind.length} characters")
        return text
    if isinstance(kind, Boolean):
        if not isinstance(value, bool):
            raise ValueError(f"{column.name}: not true or false")
        return value
    if isinstance(kind, SmallInteger | Integer | BigInteger):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{column.name}: not a whole number")
        return value
    if isinstance(kind, Float):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{column.name}: not a number")
        return float(value)
    if isinstance(kind, ARRAY):
        if not isinstance(value, list):
            raise ValueError(f"{column.name}: not a list")
        return value
    if isinstance(kind, JSONB):
        return value
    raise ValueError(f"{column.name}: unsupported type {kind}")


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("expected text")
    return value
