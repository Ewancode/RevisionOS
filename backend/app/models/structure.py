"""Academic structure: years own modules; modules own a tree of topics.

Ownership is enforced by the database as well as the repositories: composite
foreign keys tie each row's user_id to its parent's, and a topic's parent
must be in the same module (ARCHITECTURE.md section 5, design rule 1).
"""

import uuid
from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import CreatedAt, OptionalTimestamp, UpdatedAt, UUIDPk

MODULE_STATUSES = ("active", "archived")


class AcademicYear(Base):
    __tablename__ = "academic_years"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(40))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(server_default=text("false"), default=False)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_academic_years_id_user"),
        UniqueConstraint("user_id", "label", name="uq_academic_years_user_label"),
        CheckConstraint("end_date > start_date", name="dates_ordered"),
        # At most one current year per user.
        Index(
            "uq_academic_years_one_current",
            "user_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )


class Module(Base):
    __tablename__ = "modules"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    academic_year_id: Mapped[uuid.UUID]
    code: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    subject_tag: Mapped[str | None] = mapped_column(String(60))
    credits: Mapped[int | None] = mapped_column(SmallInteger)
    colour: Mapped[str | None] = mapped_column(String(7))
    status: Mapped[str] = mapped_column(
        Enum(*MODULE_STATUSES, name="module_status"), server_default="active", default="active"
    )
    deleted_at: Mapped[OptionalTimestamp]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    __table_args__ = (
        ForeignKeyConstraint(
            ["academic_year_id", "user_id"],
            ["academic_years.id", "academic_years.user_id"],
            name="fk_modules_year_same_user",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "user_id", name="uq_modules_id_user"),
        # Codes are unique within a year among modules not in the trash.
        Index(
            "uq_modules_year_code_live",
            "academic_year_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_modules_user_year", "user_id", "academic_year_id"),
        CheckConstraint("credits IS NULL OR (credits BETWEEN 0 AND 120)", name="credits_range"),
        CheckConstraint("colour IS NULL OR colour ~ '^#[0-9a-f]{6}$'", name="colour_hex"),
    )


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    module_id: Mapped[uuid.UUID]
    parent_id: Mapped[uuid.UUID | None]
    title: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(SmallInteger)
    importance: Mapped[int] = mapped_column(SmallInteger, server_default="3", default=3)
    deleted_at: Mapped[OptionalTimestamp]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    __table_args__ = (
        ForeignKeyConstraint(
            ["module_id", "user_id"],
            ["modules.id", "modules.user_id"],
            name="fk_topics_module_same_user",
            ondelete="CASCADE",
        ),
        # A parent must be in the same module (checked only when parent_id is set).
        ForeignKeyConstraint(
            ["parent_id", "module_id"],
            ["topics.id", "topics.module_id"],
            name="fk_topics_parent_same_module",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "module_id", name="uq_topics_id_module"),
        Index("ix_topics_module_parent", "module_id", "parent_id"),
        CheckConstraint("importance BETWEEN 1 AND 5", name="importance_range"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
    )
