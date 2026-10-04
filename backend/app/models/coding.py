"""Coding exercises, submissions and tutor hints (ARCHITECTURE.md sections 5
and 9; SPEC 37, 38, 69).

Code runs in the browser; the server stores the exercise, each submission
and its test results as reported by the browser, and the hints given.
"""

import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import CreatedAt, OptionalTimestamp, UpdatedAt, UUIDPk
from app.models.practice import ORIGINS, _placement
from app.practice.answers import DIFFICULTIES

LANGUAGES = ("python", "r")
HINT_LEVELS = 5


class CodingExercise(Base):
    __tablename__ = "coding_exercises"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    module_id: Mapped[uuid.UUID]
    topic_id: Mapped[uuid.UUID | None]
    language: Mapped[str] = mapped_column(Enum(*LANGUAGES, name="coding_language"))
    title: Mapped[str] = mapped_column(String(200))
    prompt_md: Mapped[str] = mapped_column(Text)
    starter_code: Mapped[str] = mapped_column(Text)
    solution_code: Mapped[str] = mapped_column(Text)
    # [{name, code, hidden}]: each test is code run after yours, in the same
    # namespace; it passes unless it raises (an assert, or stop() in R).
    tests: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    packages: Mapped[list[str]] = mapped_column(JSONB, server_default="[]", default=list)
    difficulty: Mapped[str] = mapped_column(
        Enum(*DIFFICULTIES, name="question_difficulty", create_type=False)
    )
    origin: Mapped[str] = mapped_column(Enum(*ORIGINS, name="content_origin", create_type=False))
    # Assessed coursework: hints and error-checking only, never the solution
    # (ARCHITECTURE.md section 18, academic integrity).
    assessed: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]", default=list)
    deleted_at: Mapped[OptionalTimestamp]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    __table_args__ = (
        *_placement("coding_exercises"),
        UniqueConstraint("id", "user_id", name="uq_coding_exercises_id_user"),
        Index("ix_coding_exercises_user_module", "user_id", "module_id"),
    )


class CodingSubmission(Base):
    """One "Submit": your code and the test results your browser reported."""

    __tablename__ = "coding_submissions"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    exercise_id: Mapped[uuid.UUID]
    code: Mapped[str] = mapped_column(Text)
    # [{name, passed, message}], in the exercise's test order.
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    passed: Mapped[int] = mapped_column(SmallInteger)
    total: Mapped[int] = mapped_column(SmallInteger)
    error: Mapped[str | None] = mapped_column(Text)
    runtime_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        ForeignKeyConstraint(
            ["exercise_id", "user_id"],
            ["coding_exercises.id", "coding_exercises.user_id"],
            name="fk_coding_submissions_exercise_same_user",
            ondelete="CASCADE",
        ),
        CheckConstraint("passed >= 0 AND passed <= total", name="passed_range"),
        Index("ix_coding_submissions_exercise", "exercise_id", "created_at"),
    )


class TutorHint(Base):
    """A rung of the hint ladder, for a coding exercise or an answer in a
    practice quiz. The server decides which rung comes next."""

    __tablename__ = "tutor_hints"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    exercise_id: Mapped[uuid.UUID | None]
    question_attempt_id: Mapped[uuid.UUID | None]
    level: Mapped[int] = mapped_column(SmallInteger)
    content_md: Mapped[str] = mapped_column(Text)
    ai_interaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_interactions.id", ondelete="SET NULL")
    )
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        ForeignKeyConstraint(
            ["exercise_id", "user_id"],
            ["coding_exercises.id", "coding_exercises.user_id"],
            name="fk_tutor_hints_exercise_same_user",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["question_attempt_id", "user_id"],
            ["question_attempts.id", "question_attempts.user_id"],
            name="fk_tutor_hints_answer_same_user",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(exercise_id IS NULL) <> (question_attempt_id IS NULL)", name="one_target"
        ),
        CheckConstraint(f"level BETWEEN 1 AND {HINT_LEVELS}", name="level_range"),
        UniqueConstraint("exercise_id", "level", name="uq_tutor_hints_exercise_level"),
        UniqueConstraint("question_attempt_id", "level", name="uq_tutor_hints_answer_level"),
    )
