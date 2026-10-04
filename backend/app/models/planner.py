"""The revision planner: exams, availability, the plan and its sessions,
and in-app notifications (ARCHITECTURE.md sections 5 and 11)."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import CreatedAt, OptionalTimestamp, UpdatedAt, UUIDPk

SESSION_KINDS = ("topic", "mock_exam")
SESSION_STATUSES = ("planned", "done", "missed", "skipped")


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    module_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String(200))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(SmallInteger)
    location: Mapped[str | None] = mapped_column(String(200))
    # Share of the module's mark, in percent (None: not known).
    weighting: Mapped[int | None] = mapped_column(SmallInteger)
    # How ready you feel, 1-5 (None: not said).
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    __table_args__ = (
        ForeignKeyConstraint(
            ["module_id", "user_id"],
            ["modules.id", "modules.user_id"],
            name="fk_exams_module_same_user",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "user_id", name="uq_exams_id_user"),
        UniqueConstraint("id", "module_id", name="uq_exams_id_module"),
        CheckConstraint("weighting IS NULL OR weighting BETWEEN 1 AND 100", name="weighting_range"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 1 AND 5", name="confidence_range"
        ),
        CheckConstraint("duration_minutes BETWEEN 1 AND 600", name="duration_range"),
        Index("ix_exams_user_starts", "user_id", "starts_at"),
    )


class ExamTopic(Base):
    """Topics an exam covers (none listed: the whole module)."""

    __tablename__ = "exam_topics"

    exam_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    topic_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    module_id: Mapped[uuid.UUID]

    __table_args__ = (
        ForeignKeyConstraint(
            ["exam_id", "module_id"],
            ["exams.id", "exams.module_id"],
            name="fk_exam_topics_exam_same_module",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["topic_id", "module_id"],
            ["topics.id", "topics.module_id"],
            name="fk_exam_topics_topic_same_module",
            ondelete="CASCADE",
        ),
    )


class AvailabilityRule(Base):
    """Minutes available on each weekday (0 Monday ... 6 Sunday)."""

    __tablename__ = "availability_rules"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    minutes: Mapped[int] = mapped_column(SmallInteger)

    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("minutes BETWEEN 0 AND 1440", name="minutes_range"),
    )


class AvailabilityOverride(Base):
    """A specific date's minutes, replacing its weekday's ("2 hours today")."""

    __tablename__ = "availability_overrides"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    minutes: Mapped[int] = mapped_column(SmallInteger)
    note: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (CheckConstraint("minutes BETWEEN 0 AND 1440", name="minutes_range"),)


class RevisionPlan(Base):
    """One computation of the plan; the newest is current."""

    __tablename__ = "revision_plans"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Inputs in brief, and any shortfall ("14 h needed, 9 available ...").
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    shortfalls: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default="[]", default=list
    )

    __table_args__ = (Index("ix_revision_plans_user_generated", "user_id", "generated_at"),)


class StudySession(Base):
    __tablename__ = "study_sessions"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("revision_plans.id", ondelete="SET NULL")
    )
    module_id: Mapped[uuid.UUID]
    topic_id: Mapped[uuid.UUID | None]
    exam_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("exams.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(Enum(*SESSION_KINDS, name="session_kind"))
    day: Mapped[date] = mapped_column(Date)
    minutes: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(
        Enum(*SESSION_STATUSES, name="session_status"), server_default="planned"
    )
    # Moved or edited by you: the planner never moves it again.
    locked: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    actual_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    completed_at: Mapped[OptionalTimestamp]
    # The engine's factors, e.g. "est. 43% · exam in 34 days".
    reason: Mapped[str] = mapped_column(Text, server_default="", default="")
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        ForeignKeyConstraint(
            ["module_id", "user_id"],
            ["modules.id", "modules.user_id"],
            name="fk_study_sessions_module_same_user",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["topic_id", "module_id"],
            ["topics.id", "topics.module_id"],
            name="fk_study_sessions_topic_same_module",
            ondelete="CASCADE",
        ),
        CheckConstraint("minutes BETWEEN 1 AND 1440", name="minutes_range"),
        Index("ix_study_sessions_user_day", "user_id", "day"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, server_default="", default="")
    link: Mapped[str | None] = mapped_column(String(300))
    # Each reminder is made once (e.g. "exam:<id>:7").
    dedupe_key: Mapped[str] = mapped_column(String(200))
    read_at: Mapped[OptionalTimestamp]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_once"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )
