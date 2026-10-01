"""Documents, extracted pages, and AI interactions and usage.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01 18:08:03.885988
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.Uuid(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("mime", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("source_tier", sa.Enum("university", "own", name="source_tier"), nullable=False),
        sa.Column(
            "material_kind",
            sa.Enum(
                "lecture",
                "problem_sheet",
                "solutions",
                "past_paper",
                "notes",
                "other",
                name="material_kind",
            ),
            nullable=False,
        ),
        sa.Column("week", sa.SmallInteger(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("queued", "processing", "ready", "failed", name="document_status"),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("stage", sa.String(length=40), server_default="queued", nullable=False),
        sa.Column("progress", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("page_count", sa.SmallInteger(), nullable=True),
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
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name=op.f("ck_documents_progress_range")),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_documents_size_positive")),
        sa.CheckConstraint(
            "week IS NULL OR week BETWEEN 0 AND 60", name=op.f("ck_documents_week_range")
        ),
        sa.ForeignKeyConstraint(
            ["module_id", "user_id"],
            ["modules.id", "modules.user_id"],
            name="fk_documents_module_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id", "module_id"],
            ["topics.id", "topics.module_id"],
            name="fk_documents_topic_same_module",
            ondelete="SET NULL (topic_id)",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_documents_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_documents_storage_key")),
    )
    op.create_index("ix_documents_user_module", "documents", ["user_id", "module_id"], unique=False)
    op.create_index(
        "uq_documents_user_sha256_live",
        "documents",
        ["user_id", "sha256"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "ai_interactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("feature", sa.String(length=64), nullable=False),
        sa.Column("requested_model", sa.String(length=100), nullable=False),
        sa.Column("served_model", sa.String(length=100), nullable=True),
        sa.Column("effort", sa.String(length=10), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ok", "refused", "error", "budget_blocked", name="ai_interaction_status"),
            nullable=False,
        ),
        sa.Column("stop_reason", sa.String(length=32), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_ai_interactions_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_ai_interactions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_interactions")),
    )
    op.create_index(
        "ix_ai_interactions_user_created",
        "ai_interactions",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "document_pages",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("page_no", sa.SmallInteger(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column(
            "extraction_method",
            sa.Enum("text", "vision", "corrected", "unreadable", name="extraction_method"),
            nullable=False,
        ),
        sa.Column("maths_damage_score", sa.Float(), server_default="0", nullable=False),
        sa.Column("needs_review", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("review_note", sa.String(length=300), nullable=True),
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
            "maths_damage_score BETWEEN 0 AND 1",
            name=op.f("ck_document_pages_maths_damage_score_range"),
        ),
        sa.CheckConstraint("page_no >= 1", name=op.f("ck_document_pages_page_no_positive")),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_pages_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", "page_no", name=op.f("pk_document_pages")),
    )
    op.create_table(
        "ai_usage",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("interaction_id", sa.Uuid(), nullable=False),
        sa.Column("feature", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("module_id", sa.Uuid(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["interaction_id"],
            ["ai_interactions.id"],
            name=op.f("fk_ai_usage_interaction_id_ai_interactions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["modules.id"],
            name=op.f("fk_ai_usage_module_id_modules"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_ai_usage_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_usage")),
    )
    op.create_index("ix_ai_usage_user_created", "ai_usage", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ai_usage_user_created", table_name="ai_usage")
    op.drop_table("ai_usage")
    op.drop_table("document_pages")
    op.drop_index("ix_ai_interactions_user_created", table_name="ai_interactions")
    op.drop_table("ai_interactions")
    op.drop_index(
        "uq_documents_user_sha256_live",
        table_name="documents",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("ix_documents_user_module", table_name="documents")
    op.drop_table("documents")
    # Enum types outlive their tables unless dropped explicitly.
    for name in (
        "extraction_method",
        "ai_interaction_status",
        "document_status",
        "material_kind",
        "source_tier",
    ):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=False)
