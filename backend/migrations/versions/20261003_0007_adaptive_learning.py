"""Adaptive learning: FSRS state and reviews, topic mastery, profile
snapshots; daily quizzes (spanning modules).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Flashcards: FSRS scheduling state; (id, user_id) is the reviews' FK target.
    op.add_column(
        "flashcards", sa.Column("fsrs_state", sa.SmallInteger(), server_default="1", nullable=False)
    )
    op.add_column(
        "flashcards", sa.Column("fsrs_step", sa.SmallInteger(), server_default="0", nullable=True)
    )
    op.add_column("flashcards", sa.Column("stability", sa.Float(), nullable=True))
    op.add_column("flashcards", sa.Column("fsrs_difficulty", sa.Float(), nullable=True))
    op.add_column(
        "flashcards",
        sa.Column(
            "due", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.add_column("flashcards", sa.Column("last_review", sa.DateTime(timezone=True), nullable=True))
    op.add_column("flashcards", sa.Column("reps", sa.Integer(), server_default="0", nullable=False))
    op.add_column(
        "flashcards", sa.Column("lapses", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_index("ix_flashcards_user_due", "flashcards", ["user_id", "due"], unique=False)
    op.create_unique_constraint("uq_flashcards_id_user", "flashcards", ["id", "user_id"])

    op.create_table(
        "flashcard_reviews",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("flashcard_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state_before", sa.SmallInteger(), nullable=False),
        sa.Column("elapsed_days", sa.Float(), nullable=True),
        sa.Column("stability", sa.Float(), nullable=True),
        sa.Column("difficulty", sa.Float(), nullable=True),
        sa.Column("scheduled_days", sa.Float(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "rating BETWEEN 1 AND 4", name=op.f("ck_flashcard_reviews_rating_range")
        ),
        sa.ForeignKeyConstraint(
            ["flashcard_id", "user_id"],
            ["flashcards.id", "flashcards.user_id"],
            name="fk_flashcard_reviews_card_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_flashcard_reviews_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flashcard_reviews")),
    )
    op.create_index(
        "ix_flashcard_reviews_user_reviewed",
        "flashcard_reviews",
        ["user_id", "reviewed_at"],
        unique=False,
    )

    op.create_table(
        "topic_mastery",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.Uuid(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=True),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=False),
        sa.Column("retrievability", sa.Float(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("ability", sa.Float(), nullable=False),
        sa.Column("last_practised_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "strength BETWEEN 0 AND 1", name=op.f("ck_topic_mastery_strength_range")
        ),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["modules.id"],
            name=op.f("fk_topic_mastery_module_id_modules"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["topics.id"],
            name=op.f("fk_topic_mastery_topic_id_topics"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_topic_mastery_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_topic_mastery")),
        sa.UniqueConstraint(
            "user_id",
            "module_id",
            "topic_id",
            name="uq_topic_mastery_bucket",
            postgresql_nulls_not_distinct=True,
        ),
    )

    op.create_table(
        "learning_profile_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary_md", sa.Text(), nullable=True),
        sa.Column("ai_interaction_id", sa.Uuid(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ai_interaction_id"],
            ["ai_interactions.id"],
            name=op.f("fk_learning_profile_snapshots_ai_interaction_id_ai_interactions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_learning_profile_snapshots_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learning_profile_snapshots")),
        sa.UniqueConstraint("user_id", "week_start", name="uq_profile_week"),
    )

    # Daily quizzes span modules.
    op.execute("ALTER TYPE quiz_kind ADD VALUE IF NOT EXISTS 'daily'")
    op.alter_column("quizzes", "module_id", existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM quizzes WHERE kind = 'daily' OR module_id IS NULL")
    op.alter_column("quizzes", "module_id", existing_type=sa.UUID(), nullable=False)
    # PostgreSQL cannot drop an enum value: rebuild the type without it.
    op.execute("ALTER TYPE quiz_kind RENAME TO quiz_kind_old")
    op.execute("CREATE TYPE quiz_kind AS ENUM ('practice', 'mock')")
    op.execute("ALTER TABLE quizzes ALTER COLUMN kind TYPE quiz_kind USING kind::text::quiz_kind")
    op.execute("DROP TYPE quiz_kind_old")

    op.drop_table("learning_profile_snapshots")
    op.drop_table("topic_mastery")
    op.drop_index("ix_flashcard_reviews_user_reviewed", table_name="flashcard_reviews")
    op.drop_table("flashcard_reviews")
    op.drop_constraint("uq_flashcards_id_user", "flashcards", type_="unique")
    op.drop_index("ix_flashcards_user_due", table_name="flashcards")
    for column in (
        "lapses",
        "reps",
        "last_review",
        "due",
        "fsrs_difficulty",
        "stability",
        "fsrs_step",
        "fsrs_state",
    ):
        op.drop_column("flashcards", column)
