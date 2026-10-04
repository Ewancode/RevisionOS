"""Revision planner: exams, availability, plans and sessions, notifications;
planner and notification preferences.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-04 15:06:22.542833
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "availability_overrides",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("minutes", sa.SmallInteger(), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.CheckConstraint(
            "minutes BETWEEN 0 AND 1440", name=op.f("ck_availability_overrides_minutes_range")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_availability_overrides_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "day", name=op.f("pk_availability_overrides")),
    )
    op.create_table(
        "availability_rules",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("minutes", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "minutes BETWEEN 0 AND 1440", name=op.f("ck_availability_rules_minutes_range")
        ),
        sa.CheckConstraint(
            "weekday BETWEEN 0 AND 6", name=op.f("ck_availability_rules_weekday_range")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_availability_rules_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "weekday", name=op.f("pk_availability_rules")),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), server_default="", nullable=False),
        sa.Column("link", sa.String(length=300), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_once"),
    )
    op.create_index(
        "ix_notifications_user_created", "notifications", ["user_id", "created_at"], unique=False
    )
    op.create_table(
        "revision_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "shortfalls",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_revision_plans_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_revision_plans")),
    )
    op.create_index(
        "ix_revision_plans_user_generated",
        "revision_plans",
        ["user_id", "generated_at"],
        unique=False,
    )
    op.create_table(
        "exams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("weighting", sa.SmallInteger(), nullable=True),
        sa.Column("confidence", sa.SmallInteger(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 1 AND 5",
            name=op.f("ck_exams_confidence_range"),
        ),
        sa.CheckConstraint(
            "duration_minutes BETWEEN 1 AND 600", name=op.f("ck_exams_duration_range")
        ),
        sa.CheckConstraint(
            "weighting IS NULL OR weighting BETWEEN 1 AND 100",
            name=op.f("ck_exams_weighting_range"),
        ),
        sa.ForeignKeyConstraint(
            ["module_id", "user_id"],
            ["modules.id", "modules.user_id"],
            name="fk_exams_module_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_exams_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exams")),
        sa.UniqueConstraint("id", "module_id", name="uq_exams_id_module"),
        sa.UniqueConstraint("id", "user_id", name="uq_exams_id_user"),
    )
    op.create_index("ix_exams_user_starts", "exams", ["user_id", "starts_at"], unique=False)
    op.create_table(
        "exam_topics",
        sa.Column("exam_id", sa.Uuid(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["exam_id", "module_id"],
            ["exams.id", "exams.module_id"],
            name="fk_exam_topics_exam_same_module",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id", "module_id"],
            ["topics.id", "topics.module_id"],
            name="fk_exam_topics_topic_same_module",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("exam_id", "topic_id", name=op.f("pk_exam_topics")),
    )
    op.create_table(
        "study_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=True),
        sa.Column("module_id", sa.Uuid(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=True),
        sa.Column("exam_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Enum("topic", "mock_exam", name="session_kind"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("minutes", sa.SmallInteger(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("planned", "done", "missed", "skipped", name="session_status"),
            server_default="planned",
            nullable=False,
        ),
        sa.Column("locked", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("actual_minutes", sa.SmallInteger(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "minutes BETWEEN 1 AND 1440", name=op.f("ck_study_sessions_minutes_range")
        ),
        sa.ForeignKeyConstraint(
            ["exam_id"],
            ["exams.id"],
            name=op.f("fk_study_sessions_exam_id_exams"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["module_id", "user_id"],
            ["modules.id", "modules.user_id"],
            name="fk_study_sessions_module_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["revision_plans.id"],
            name=op.f("fk_study_sessions_plan_id_revision_plans"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id", "module_id"],
            ["topics.id", "topics.module_id"],
            name="fk_study_sessions_topic_same_module",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_study_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_study_sessions")),
    )
    op.create_index(
        "ix_study_sessions_user_day", "study_sessions", ["user_id", "day"], unique=False
    )
    op.add_column("user_settings", sa.Column("session_minutes", sa.SmallInteger(), nullable=True))
    op.add_column(
        "user_settings", sa.Column("max_sessions_per_day", sa.SmallInteger(), nullable=True)
    )
    op.add_column(
        "user_settings",
        sa.Column(
            "rest_weekdays",
            postgresql.ARRAY(sa.SmallInteger()),
            server_default="{}",
            nullable=False,
        ),
    )
    op.add_column(
        "user_settings",
        sa.Column("notify_exams", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "user_settings",
        sa.Column("notify_quiz", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "user_settings",
        sa.Column("notify_neglected", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "user_settings",
        sa.Column("notify_flashcards", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "user_settings", sa.Column("quiz_reminder_hour", sa.SmallInteger(), nullable=True)
    )
    op.add_column("user_settings", sa.Column("quiet_from", sa.SmallInteger(), nullable=True))
    op.add_column("user_settings", sa.Column("quiet_to", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_settings", "quiet_to")
    op.drop_column("user_settings", "quiet_from")
    op.drop_column("user_settings", "quiz_reminder_hour")
    op.drop_column("user_settings", "notify_flashcards")
    op.drop_column("user_settings", "notify_neglected")
    op.drop_column("user_settings", "notify_quiz")
    op.drop_column("user_settings", "notify_exams")
    op.drop_column("user_settings", "rest_weekdays")
    op.drop_column("user_settings", "max_sessions_per_day")
    op.drop_column("user_settings", "session_minutes")
    op.drop_index("ix_study_sessions_user_day", table_name="study_sessions")
    op.drop_table("study_sessions")
    op.drop_table("exam_topics")
    op.drop_index("ix_exams_user_starts", table_name="exams")
    op.drop_table("exams")
    op.drop_index("ix_revision_plans_user_generated", table_name="revision_plans")
    op.drop_table("revision_plans")
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("availability_rules")
    op.drop_table("availability_overrides")
    for enum in ("session_status", "session_kind"):
        sa.Enum(name=enum).drop(op.get_bind(), checkfirst=False)
