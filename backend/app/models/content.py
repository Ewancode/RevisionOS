"""Uploaded documents and their extracted pages (ARCHITECTURE.md sections 5-7)."""

import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import CreatedAt, OptionalTimestamp, UpdatedAt, UUIDPk

SOURCE_TIERS = ("university", "own")
MATERIAL_KINDS = ("lecture", "problem_sheet", "solutions", "past_paper", "notes", "other")
DOCUMENT_STATUSES = ("queued", "processing", "ready", "failed")
EXTRACTION_METHODS = ("text", "vision", "corrected", "unreadable")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    module_id: Mapped[uuid.UUID]
    topic_id: Mapped[uuid.UUID | None]

    # Display only, sanitised. Never used to build a storage path.
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    mime: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[bytes] = mapped_column(LargeBinary(32))

    source_tier: Mapped[str] = mapped_column(Enum(*SOURCE_TIERS, name="source_tier"))
    material_kind: Mapped[str] = mapped_column(Enum(*MATERIAL_KINDS, name="material_kind"))
    week: Mapped[int | None] = mapped_column(SmallInteger)

    status: Mapped[str] = mapped_column(
        Enum(*DOCUMENT_STATUSES, name="document_status"), server_default="queued", default="queued"
    )
    stage: Mapped[str] = mapped_column(String(40), server_default="queued", default="queued")
    progress: Mapped[int] = mapped_column(SmallInteger, server_default="0", default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    page_count: Mapped[int | None] = mapped_column(SmallInteger)

    deleted_at: Mapped[OptionalTimestamp]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    __table_args__ = (
        ForeignKeyConstraint(
            ["module_id", "user_id"],
            ["modules.id", "modules.user_id"],
            name="fk_documents_module_same_user",
            ondelete="CASCADE",
        ),
        # A topic, when given, must belong to the document's module.
        ForeignKeyConstraint(
            ["topic_id", "module_id"],
            ["topics.id", "topics.module_id"],
            name="fk_documents_topic_same_module",
            ondelete="SET NULL (topic_id)",
        ),
        # The same file is stored once per user (among documents not in the trash).
        Index(
            "uq_documents_user_sha256_live",
            "user_id",
            "sha256",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_documents_user_module", "user_id", "module_id"),
        UniqueConstraint("id", "user_id", name="uq_documents_id_user"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="progress_range"),
        CheckConstraint("week IS NULL OR week BETWEEN 0 AND 60", name="week_range"),
        CheckConstraint("size_bytes >= 0", name="size_positive"),
    )


class DocumentPage(Base):
    """One page, slide, sheet or section as Markdown with LaTeX maths."""

    __tablename__ = "document_pages"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    page_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    markdown: Mapped[str] = mapped_column(Text)
    extraction_method: Mapped[str] = mapped_column(
        Enum(*EXTRACTION_METHODS, name="extraction_method")
    )
    maths_damage_score: Mapped[float] = mapped_column(Float, server_default="0", default=0.0)
    # Set when a page needs a human look: low-confidence transcription, or a
    # damaged page that could not be transcribed (budget, no key, error).
    needs_review: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    review_note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    __table_args__ = (
        CheckConstraint("page_no >= 1", name="page_no_positive"),
        CheckConstraint("maths_damage_score BETWEEN 0 AND 1", name="maths_damage_score_range"),
    )
