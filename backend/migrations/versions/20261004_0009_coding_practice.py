"""coding practice: exercises, submissions and tutor hints

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-04 16:24:36.988766
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE draft_kind ADD VALUE IF NOT EXISTS 'coding'")
    op.create_table(
        "coding_exercises",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.Uuid(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=True),
        sa.Column("language", sa.Enum("python", "r", name="coding_language"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("prompt_md", sa.Text(), nullable=False),
        sa.Column("starter_code", sa.Text(), nullable=False),
        sa.Column("solution_code", sa.Text(), nullable=False),
        sa.Column("tests", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "packages", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column(
            "difficulty",
            postgresql.ENUM(name="question_difficulty", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "origin", postgresql.ENUM(name="content_origin", create_type=False), nullable=False
        ),
        sa.Column("assessed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "sources", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
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
        sa.ForeignKeyConstraint(
            ["module_id", "user_id"],
            ["modules.id", "modules.user_id"],
            name="fk_coding_exercises_module_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id", "module_id"],
            ["topics.id", "topics.module_id"],
            name="fk_coding_exercises_topic_same_module",
            ondelete="SET NULL (topic_id)",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_coding_exercises_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coding_exercises")),
        sa.UniqueConstraint("id", "user_id", name="uq_coding_exercises_id_user"),
    )
    op.create_index(
        "ix_coding_exercises_user_module",
        "coding_exercises",
        ["user_id", "module_id"],
        unique=False,
    )
    op.create_table(
        "coding_submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("exercise_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("passed", sa.SmallInteger(), nullable=False),
        sa.Column("total", sa.SmallInteger(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("runtime_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "passed >= 0 AND passed <= total", name=op.f("ck_coding_submissions_passed_range")
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id", "user_id"],
            ["coding_exercises.id", "coding_exercises.user_id"],
            name="fk_coding_submissions_exercise_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_coding_submissions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coding_submissions")),
    )
    op.create_index(
        "ix_coding_submissions_exercise",
        "coding_submissions",
        ["exercise_id", "created_at"],
        unique=False,
    )
    # Hints point at an answer and its owner together (tutor_hints below).
    op.create_unique_constraint(
        "uq_question_attempts_id_user", "question_attempts", ["id", "user_id"]
    )
    op.create_table(
        "tutor_hints",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("exercise_id", sa.Uuid(), nullable=True),
        sa.Column("question_attempt_id", sa.Uuid(), nullable=True),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("ai_interaction_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(exercise_id IS NULL) <> (question_attempt_id IS NULL)",
            name=op.f("ck_tutor_hints_one_target"),
        ),
        sa.CheckConstraint("level BETWEEN 1 AND 5", name=op.f("ck_tutor_hints_level_range")),
        sa.ForeignKeyConstraint(
            ["ai_interaction_id"],
            ["ai_interactions.id"],
            name=op.f("fk_tutor_hints_ai_interaction_id_ai_interactions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id", "user_id"],
            ["coding_exercises.id", "coding_exercises.user_id"],
            name="fk_tutor_hints_exercise_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["question_attempt_id", "user_id"],
            ["question_attempts.id", "question_attempts.user_id"],
            name="fk_tutor_hints_answer_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_tutor_hints_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutor_hints")),
        sa.UniqueConstraint("exercise_id", "level", name="uq_tutor_hints_exercise_level"),
        sa.UniqueConstraint("question_attempt_id", "level", name="uq_tutor_hints_answer_level"),
    )


def downgrade() -> None:
    op.drop_table("tutor_hints")
    op.drop_constraint("uq_question_attempts_id_user", "question_attempts", type_="unique")
    op.drop_index("ix_coding_submissions_exercise", table_name="coding_submissions")
    op.drop_table("coding_submissions")
    op.drop_index("ix_coding_exercises_user_module", table_name="coding_exercises")
    op.drop_table("coding_exercises")
    op.execute("DROP TYPE coding_language")
    op.execute("DELETE FROM drafts WHERE kind = 'coding'")
    op.execute("ALTER TYPE draft_kind RENAME TO draft_kind_old")
    op.execute("CREATE TYPE draft_kind AS ENUM ('material', 'questions', 'flashcards')")
    op.execute("ALTER TABLE drafts ALTER COLUMN kind TYPE draft_kind USING kind::text::draft_kind")
    op.execute("DROP TYPE draft_kind_old")
