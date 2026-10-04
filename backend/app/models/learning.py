"""Facts and derived state for adaptive learning (ARCHITECTURE.md section 10).

Flashcard reviews are append-only facts. Topic mastery and the learning
profile are derived from facts and can be recomputed at any time.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import OptionalTimestamp


class FlashcardReview(Base):
    __tablename__ = "flashcard_reviews"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    flashcard_id: Mapped[uuid.UUID]
    # 1 Again, 2 Hard, 3 Good, 4 Easy.
    rating: Mapped[int] = mapped_column(SmallInteger)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state_before: Mapped[int] = mapped_column(SmallInteger)
    # Days since the previous review (None for a card's first review).
    elapsed_days: Mapped[float | None] = mapped_column(Float)
    # The card after this review.
    stability: Mapped[float | None] = mapped_column(Float)
    difficulty: Mapped[float | None] = mapped_column(Float)
    scheduled_days: Mapped[float] = mapped_column(Float)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        ForeignKeyConstraint(
            ["flashcard_id", "user_id"],
            ["flashcards.id", "flashcards.user_id"],
            name="fk_flashcard_reviews_card_same_user",
            ondelete="CASCADE",
        ),
        CheckConstraint("rating BETWEEN 1 AND 4", name="rating_range"),
        Index("ix_flashcard_reviews_user_reviewed", "user_id", "reviewed_at"),
    )


class TopicMastery(Base):
    """Derived per topic (or per module, for questions with no topic):
    recomputed from attempts and reviews after each change."""

    __tablename__ = "topic_mastery"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    module_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"))
    strength: Mapped[float] = mapped_column(Float)
    accuracy: Mapped[float] = mapped_column(Float)
    retrievability: Mapped[float | None] = mapped_column(Float)
    # Total attempt weight behind the estimate ("low data" below a threshold).
    weight: Mapped[float] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(Integer)
    # Elo-style ability.
    ability: Mapped[float] = mapped_column(Float)
    last_practised_at: Mapped[OptionalTimestamp]
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "module_id",
            "topic_id",
            name="uq_topic_mastery_bucket",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("strength BETWEEN 0 AND 1", name="strength_range"),
    )


class LearningProfileSnapshot(Base):
    """Weekly measured statistics, with Claude's short summary of them."""

    __tablename__ = "learning_profile_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    week_start: Mapped[date] = mapped_column(Date)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    summary_md: Mapped[str | None] = mapped_column(Text)
    ai_interaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_interactions.id", ondelete="SET NULL")
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("user_id", "week_start", name="uq_profile_week"),)
