"""Exports of your data and restores from them (SPEC 50; ARCHITECTURE.md
section 15, Phase 13)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import CreatedAt, UUIDPk

JOB_KINDS = ("export", "restore")
JOB_STATUSES = ("queued", "running", "done", "failed")


class DataJob(Base):
    """One export (building a ZIP) or restore (reading one back)."""

    __tablename__ = "data_jobs"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Enum(*JOB_KINDS, name="data_job_kind"))
    status: Mapped[str] = mapped_column(
        Enum(*JOB_STATUSES, name="data_job_status"), default="queued"
    )
    # The archive in storage: the export built, or the upload being restored.
    storage_key: Mapped[str | None] = mapped_column(String(200))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    # Rows per table written or restored, shown to you when it finishes.
    counts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[CreatedAt]
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_data_jobs_user_created", "user_id", "created_at"),)
