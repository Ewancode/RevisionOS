"""Identity (users, settings, sessions, audit log) and academic structure.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01 17:13:19.648739
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
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
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_lowercase")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "academic_years",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=40), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.CheckConstraint("end_date > start_date", name=op.f("ck_academic_years_dates_ordered")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_academic_years_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_academic_years")),
        sa.UniqueConstraint("id", "user_id", name="uq_academic_years_id_user"),
        sa.UniqueConstraint("user_id", "label", name="uq_academic_years_user_label"),
    )
    op.create_index(
        "uq_academic_years_one_current",
        "academic_years",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_audit_log_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(op.f("ix_audit_log_user_id"), "audit_log", ["user_id"], unique=False)
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("csrf_token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_sessions_token_hash")),
    )
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"], unique=False)
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "theme",
            sa.Enum("light", "dark", "system", name="theme"),
            server_default="system",
            nullable=False,
        ),
        sa.Column("accent_colour", sa.String(length=7), server_default="#4f46e5", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "accent_colour ~ '^#[0-9a-f]{6}$'", name=op.f("ck_user_settings_accent_colour_hex")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_settings_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_settings")),
    )
    op.create_table(
        "modules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("academic_year_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subject_tag", sa.String(length=60), nullable=True),
        sa.Column("credits", sa.SmallInteger(), nullable=True),
        sa.Column("colour", sa.String(length=7), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "archived", name="module_status"),
            server_default="active",
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
            "colour IS NULL OR colour ~ '^#[0-9a-f]{6}$'", name=op.f("ck_modules_colour_hex")
        ),
        sa.CheckConstraint(
            "credits IS NULL OR (credits BETWEEN 0 AND 120)", name=op.f("ck_modules_credits_range")
        ),
        sa.ForeignKeyConstraint(
            ["academic_year_id", "user_id"],
            ["academic_years.id", "academic_years.user_id"],
            name="fk_modules_year_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_modules_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_modules")),
        sa.UniqueConstraint("id", "user_id", name="uq_modules_id_user"),
    )
    op.create_index(
        "ix_modules_user_year", "modules", ["user_id", "academic_year_id"], unique=False
    )
    op.create_index(
        "uq_modules_year_code_live",
        "modules",
        ["academic_year_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "topics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("importance", sa.SmallInteger(), server_default="3", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("importance BETWEEN 1 AND 5", name=op.f("ck_topics_importance_range")),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id", name=op.f("ck_topics_not_own_parent")
        ),
        sa.ForeignKeyConstraint(
            ["module_id", "user_id"],
            ["modules.id", "modules.user_id"],
            name="fk_topics_module_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id", "module_id"],
            ["topics.id", "topics.module_id"],
            name="fk_topics_parent_same_module",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_topics_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_topics")),
        sa.UniqueConstraint("id", "module_id", name="uq_topics_id_module"),
    )
    op.create_index("ix_topics_module_parent", "topics", ["module_id", "parent_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_topics_module_parent", table_name="topics")
    op.drop_table("topics")
    op.drop_index(
        "uq_modules_year_code_live",
        table_name="modules",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("ix_modules_user_year", table_name="modules")
    op.drop_table("modules")
    op.drop_table("user_settings")
    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index(op.f("ix_audit_log_user_id"), table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index(
        "uq_academic_years_one_current",
        table_name="academic_years",
        postgresql_where=sa.text("is_current"),
    )
    op.drop_table("academic_years")
    op.drop_table("users")
    # Enum types outlive their tables unless dropped explicitly.
    sa.Enum(name="module_status").drop(op.get_bind(), checkfirst=False)
    sa.Enum(name="theme").drop(op.get_bind(), checkfirst=False)
