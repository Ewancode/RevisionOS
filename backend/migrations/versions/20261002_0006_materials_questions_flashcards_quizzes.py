"""Revision materials and versions, drafts, questions, flashcards, quizzes and attempts.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-02 19:00:13.648231
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "links", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
    )
    op.create_table(
        "quizzes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Enum("practice", "mock", name="quiz_kind"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("time_limit_minutes", sa.SmallInteger(), nullable=True),
        sa.Column(
            "config", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["module_id", "user_id"],
            ["modules.id", "modules.user_id"],
            name="fk_quizzes_module_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_quizzes_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quizzes")),
        sa.UniqueConstraint("id", "user_id", name="uq_quizzes_id_user"),
    )
    op.create_table(
        "flashcards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.Uuid(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=True),
        sa.Column("front_md", sa.Text(), nullable=False),
        sa.Column("back_md", sa.Text(), nullable=False),
        sa.Column("origin", sa.Enum("user", "claude", name="content_origin"), nullable=False),
        sa.Column(
            "sources", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("embedding", Vector(384), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["module_id", "user_id"],
            ["modules.id", "modules.user_id"],
            name="fk_flashcards_module_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id", "module_id"],
            ["topics.id", "topics.module_id"],
            name="fk_flashcards_topic_same_module",
            ondelete="SET NULL (topic_id)",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_flashcards_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flashcards")),
    )
    op.create_index(
        "ix_flashcards_user_module", "flashcards", ["user_id", "module_id"], unique=False
    )
    op.create_table(
        "materials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.Uuid(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "guide",
                "summary",
                "formula_sheet",
                "worked_examples",
                "definitions",
                "explanation",
                "concept_map",
                "notes",
                name="study_material_kind",
            ),
            nullable=False,
        ),
        sa.Column(
            "origin",
            postgresql.ENUM("user", "claude", name="content_origin", create_type=False),
            nullable=False,
        ),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["module_id", "user_id"],
            ["modules.id", "modules.user_id"],
            name="fk_materials_module_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id", "module_id"],
            ["topics.id", "topics.module_id"],
            name="fk_materials_topic_same_module",
            ondelete="SET NULL (topic_id)",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_materials_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_materials")),
        sa.UniqueConstraint("id", "user_id", name="uq_materials_id_user"),
    )
    op.create_index("ix_materials_user_module", "materials", ["user_id", "module_id"], unique=False)
    op.create_table(
        "questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.Uuid(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=True),
        sa.Column(
            "type",
            sa.Enum(
                "multiple_choice",
                "true_false",
                "numerical",
                "expression",
                "short_answer",
                "explanation",
                "derivation",
                name="question_type",
            ),
            nullable=False,
        ),
        sa.Column(
            "difficulty",
            sa.Enum("easy", "medium", "hard", "exam", name="question_difficulty"),
            nullable=False,
        ),
        sa.Column("rating", sa.Float(), nullable=False),
        sa.Column("stem_md", sa.Text(), nullable=False),
        sa.Column("answer_spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("solution_md", sa.Text(), nullable=False),
        sa.Column(
            "origin",
            postgresql.ENUM("user", "claude", name="content_origin", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("active", "retired", name="question_status"),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "sources", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["module_id", "user_id"],
            ["modules.id", "modules.user_id"],
            name="fk_questions_module_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id", "module_id"],
            ["topics.id", "topics.module_id"],
            name="fk_questions_topic_same_module",
            ondelete="SET NULL (topic_id)",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_questions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_questions")),
        sa.UniqueConstraint("id", "user_id", name="uq_questions_id_user"),
    )
    op.create_index("ix_questions_user_module", "questions", ["user_id", "module_id"], unique=False)
    op.create_table(
        "quiz_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("quiz_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.Enum("normal", "exam", name="attempt_mode"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("in_progress", "marking", "marked", name="attempt_status"),
            server_default="in_progress",
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("marked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["quiz_id", "user_id"],
            ["quizzes.id", "quizzes.user_id"],
            name="fk_quiz_attempts_quiz_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_quiz_attempts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_attempts")),
        sa.UniqueConstraint("id", "user_id", name="uq_quiz_attempts_id_user"),
    )
    op.create_index(
        "ix_quiz_attempts_user_status", "quiz_attempts", ["user_id", "status"], unique=False
    )
    op.create_table(
        "question_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("quiz_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column(
            "response", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column("response_image_key", sa.String(length=255), nullable=True),
        sa.Column("time_ms", sa.Integer(), nullable=True),
        sa.Column("self_confidence", sa.SmallInteger(), nullable=True),
        sa.Column("hints_used", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column(
            "marked_by", sa.Enum("rule", "sympy", "ai", "override", name="marked_by"), nullable=True
        ),
        sa.Column(
            "marking_confidence", sa.Enum("high", "medium", "low", name="confidence"), nullable=True
        ),
        sa.Column(
            "feedback", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column("mistake_category", sa.String(length=64), nullable=True),
        sa.Column("original_score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("marked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "score IS NULL OR score BETWEEN 0 AND 1", name=op.f("ck_question_attempts_score_range")
        ),
        sa.CheckConstraint(
            "self_confidence IS NULL OR self_confidence BETWEEN 1 AND 5",
            name=op.f("ck_question_attempts_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["question_id", "user_id"],
            ["questions.id", "questions.user_id"],
            name="fk_question_attempts_question_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["quiz_attempt_id", "user_id"],
            ["quiz_attempts.id", "quiz_attempts.user_id"],
            name="fk_question_attempts_attempt_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_question_attempts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_question_attempts")),
        sa.UniqueConstraint("quiz_attempt_id", "question_id", name="uq_question_attempts_once"),
    )
    op.create_index(
        "ix_question_attempts_user_question",
        "question_attempts",
        ["user_id", "question_id"],
        unique=False,
    )
    op.create_table(
        "quiz_items",
        sa.Column("quiz_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["question_id", "user_id"],
            ["questions.id", "questions.user_id"],
            name="fk_quiz_items_question_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["quiz_id", "user_id"],
            ["quizzes.id", "quizzes.user_id"],
            name="fk_quiz_items_quiz_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_quiz_items_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("quiz_id", "position", name=op.f("pk_quiz_items")),
        sa.UniqueConstraint("quiz_id", "question_id", name="uq_quiz_items_question_once"),
    )
    op.create_table(
        "drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.Uuid(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum("material", "questions", "flashcards", name="draft_kind"),
            nullable=False,
        ),
        sa.Column("request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum("generating", "ready", "failed", "saved", "discarded", name="draft_status"),
            server_default="generating",
            nullable=False,
        ),
        sa.Column(
            "payload", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("ai_interaction_id", sa.Uuid(), nullable=True),
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
            ["ai_interaction_id"],
            ["ai_interactions.id"],
            name=op.f("fk_drafts_ai_interaction_id_ai_interactions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["module_id", "user_id"],
            ["modules.id", "modules.user_id"],
            name="fk_drafts_module_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id", "module_id"],
            ["topics.id", "topics.module_id"],
            name="fk_drafts_topic_same_module",
            ondelete="SET NULL (topic_id)",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_drafts_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drafts")),
    )
    op.create_index("ix_drafts_user_module", "drafts", ["user_id", "module_id"], unique=False)
    op.create_table(
        "material_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("material_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column(
            "citations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "created_by",
            postgresql.ENUM("user", "claude", name="content_origin", create_type=False),
            nullable=False,
        ),
        sa.Column("change_note", sa.String(length=300), nullable=True),
        sa.Column("ai_interaction_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["ai_interaction_id"],
            ["ai_interactions.id"],
            name=op.f("fk_material_versions_ai_interaction_id_ai_interactions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["material_id", "user_id"],
            ["materials.id", "materials.user_id"],
            name="fk_material_versions_material_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_material_versions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_material_versions")),
        sa.UniqueConstraint("material_id", "version_no", name="uq_material_versions_number"),
    )


def downgrade() -> None:
    op.drop_column("messages", "links")
    op.drop_table("material_versions")
    op.drop_index("ix_drafts_user_module", table_name="drafts")
    op.drop_table("drafts")
    op.drop_table("quiz_items")
    op.drop_index("ix_question_attempts_user_question", table_name="question_attempts")
    op.drop_table("question_attempts")
    op.drop_index("ix_quiz_attempts_user_status", table_name="quiz_attempts")
    op.drop_table("quiz_attempts")
    op.drop_index("ix_questions_user_module", table_name="questions")
    op.drop_table("questions")
    op.drop_index("ix_materials_user_module", table_name="materials")
    op.drop_table("materials")
    op.drop_index("ix_flashcards_user_module", table_name="flashcards")
    op.drop_table("flashcards")
    op.drop_table("quizzes")
    for enum in (
        "confidence",
        "marked_by",
        "attempt_status",
        "attempt_mode",
        "draft_status",
        "draft_kind",
        "question_status",
        "question_difficulty",
        "question_type",
        "study_material_kind",
        "content_origin",
        "quiz_kind",
    ):
        sa.Enum(name=enum).drop(op.get_bind(), checkfirst=False)
