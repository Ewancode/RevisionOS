"""Revision materials, drafts, questions, flashcards, quizzes and attempts
(ARCHITECTURE.md sections 5, 9 and 10).

Every row belongs to a user and a module, enforced by composite foreign keys:
a row cannot point at another user's module, or at a topic outside its own
module. Attempts are append-only facts; scores derived from them later can
always be recomputed.
"""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
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
from app.models.retrieval import EMBEDDING_DIMENSIONS
from app.practice.answers import DIFFICULTIES, QUESTION_TYPES

MATERIAL_KINDS = (
    "guide",
    "summary",
    "formula_sheet",
    "worked_examples",
    "definitions",
    "explanation",
    "concept_map",
    "notes",
)
ORIGINS = ("user", "claude")
DRAFT_KINDS = ("material", "questions", "flashcards")
DRAFT_STATUSES = ("generating", "ready", "failed", "saved", "discarded")
QUESTION_STATUSES = ("active", "retired")
QUIZ_KINDS = ("practice", "mock")
ATTEMPT_MODES = ("normal", "exam")
ATTEMPT_STATUSES = ("in_progress", "marking", "marked")
MARKED_BY = ("rule", "sympy", "ai", "override")
CONFIDENCE = ("high", "medium", "low")


def _placement(table: str) -> tuple[ForeignKeyConstraint, ForeignKeyConstraint]:
    """The module is the owner's; the topic, if any, is in that module."""
    return (
        ForeignKeyConstraint(
            ["module_id", "user_id"],
            ["modules.id", "modules.user_id"],
            name=f"fk_{table}_module_same_user",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["topic_id", "module_id"],
            ["topics.id", "topics.module_id"],
            name=f"fk_{table}_topic_same_module",
            ondelete="SET NULL (topic_id)",
        ),
    )


class Draft(Base):
    """Generated content awaiting Save, Edit, Regenerate or Cancel (SPEC 40).
    Kept until you decide, so nothing generated is lost."""

    __tablename__ = "drafts"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    module_id: Mapped[uuid.UUID]
    topic_id: Mapped[uuid.UUID | None]
    kind: Mapped[str] = mapped_column(Enum(*DRAFT_KINDS, name="draft_kind"))
    # What was asked for: material kind, item count, difficulty, files,
    # instructions, the material being improved. Regenerate reuses it.
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        Enum(*DRAFT_STATUSES, name="draft_status"), server_default="generating"
    )
    # The generated content, with validation results per item.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    ai_interaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_interactions.id", ondelete="SET NULL")
    )
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    __table_args__ = (*_placement("drafts"), Index("ix_drafts_user_module", "user_id", "module_id"))


class Material(Base):
    __tablename__ = "materials"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    module_id: Mapped[uuid.UUID]
    topic_id: Mapped[uuid.UUID | None]
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(Enum(*MATERIAL_KINDS, name="study_material_kind"))
    # Who created it: your materials and Claude's are kept apart (SPEC 19).
    origin: Mapped[str] = mapped_column(Enum(*ORIGINS, name="content_origin"))
    current_version_id: Mapped[uuid.UUID | None]
    deleted_at: Mapped[OptionalTimestamp]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    __table_args__ = (
        *_placement("materials"),
        UniqueConstraint("id", "user_id", name="uq_materials_id_user"),
        Index("ix_materials_user_module", "user_id", "module_id"),
    )


class MaterialVersion(Base):
    """Versions are never edited: a change is a new version (SPEC 19-20)."""

    __tablename__ = "material_versions"

    id: Mapped[UUIDPk]
    material_id: Mapped[uuid.UUID]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    version_no: Mapped[int] = mapped_column(Integer)
    content_md: Mapped[str] = mapped_column(Text)
    # Verified citations, as in assistant answers.
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default="[]", default=list
    )
    created_by: Mapped[str] = mapped_column(Enum(*ORIGINS, name="content_origin"))
    change_note: Mapped[str | None] = mapped_column(String(300))
    ai_interaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_interactions.id", ondelete="SET NULL")
    )
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        ForeignKeyConstraint(
            ["material_id", "user_id"],
            ["materials.id", "materials.user_id"],
            name="fk_material_versions_material_same_user",
            ondelete="CASCADE",
        ),
        UniqueConstraint("material_id", "version_no", name="uq_material_versions_number"),
    )


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    module_id: Mapped[uuid.UUID]
    topic_id: Mapped[uuid.UUID | None]
    type: Mapped[str] = mapped_column(Enum(*QUESTION_TYPES, name="question_type"))
    difficulty: Mapped[str] = mapped_column(Enum(*DIFFICULTIES, name="question_difficulty"))
    # Elo-style difficulty; starts from the label, recalibrated in Phase 7.
    rating: Mapped[float] = mapped_column(Float)
    stem_md: Mapped[str] = mapped_column(Text)
    # Validated per type by app.practice.answers.AnswerSpec.
    answer_spec: Mapped[dict[str, Any]] = mapped_column(JSONB)
    solution_md: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Enum(*ORIGINS, name="content_origin"))
    status: Mapped[str] = mapped_column(
        Enum(*QUESTION_STATUSES, name="question_status"), server_default="active"
    )
    # Pages it was written from: [{document_id, filename, page_no, source_tier}].
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]", default=list)
    # Of the stem, for near-duplicate detection.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        *_placement("questions"),
        UniqueConstraint("id", "user_id", name="uq_questions_id_user"),
        Index("ix_questions_user_module", "user_id", "module_id"),
    )


class Flashcard(Base):
    """Scheduling state (FSRS) is added in Phase 7."""

    __tablename__ = "flashcards"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    module_id: Mapped[uuid.UUID]
    topic_id: Mapped[uuid.UUID | None]
    front_md: Mapped[str] = mapped_column(Text)
    back_md: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Enum(*ORIGINS, name="content_origin"))
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]", default=list)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    deleted_at: Mapped[OptionalTimestamp]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    __table_args__ = (
        *_placement("flashcards"),
        Index("ix_flashcards_user_module", "user_id", "module_id"),
    )


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    module_id: Mapped[uuid.UUID]
    kind: Mapped[str] = mapped_column(Enum(*QUIZ_KINDS, name="quiz_kind"))
    title: Mapped[str] = mapped_column(String(200))
    # Exam conditions: answers close at the deadline and AI help is off.
    time_limit_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    # How it was built (filters), for "practise again".
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}", default=dict)
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        ForeignKeyConstraint(
            ["module_id", "user_id"],
            ["modules.id", "modules.user_id"],
            name="fk_quizzes_module_same_user",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "user_id", name="uq_quizzes_id_user"),
    )


class QuizItem(Base):
    __tablename__ = "quiz_items"

    quiz_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    question_id: Mapped[uuid.UUID]

    __table_args__ = (
        ForeignKeyConstraint(
            ["quiz_id", "user_id"],
            ["quizzes.id", "quizzes.user_id"],
            name="fk_quiz_items_quiz_same_user",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["question_id", "user_id"],
            ["questions.id", "questions.user_id"],
            name="fk_quiz_items_question_same_user",
            ondelete="CASCADE",
        ),
        UniqueConstraint("quiz_id", "question_id", name="uq_quiz_items_question_once"),
    )


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    quiz_id: Mapped[uuid.UUID]
    mode: Mapped[str] = mapped_column(Enum(*ATTEMPT_MODES, name="attempt_mode"))
    status: Mapped[str] = mapped_column(
        Enum(*ATTEMPT_STATUSES, name="attempt_status"), server_default="in_progress"
    )
    started_at: Mapped[CreatedAt]
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[OptionalTimestamp]
    marked_at: Mapped[OptionalTimestamp]
    score: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        ForeignKeyConstraint(
            ["quiz_id", "user_id"],
            ["quizzes.id", "quizzes.user_id"],
            name="fk_quiz_attempts_quiz_same_user",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "user_id", name="uq_quiz_attempts_id_user"),
        Index("ix_quiz_attempts_user_status", "user_id", "status"),
    )


class QuestionAttempt(Base):
    """One answer to one question in one quiz attempt."""

    __tablename__ = "question_attempts"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    quiz_attempt_id: Mapped[uuid.UUID]
    question_id: Mapped[uuid.UUID]
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # A photo of handwritten working, transcribed for you to confirm.
    response_image_key: Mapped[str | None] = mapped_column(String(255))
    time_ms: Mapped[int | None] = mapped_column(Integer)
    # How sure you were, 1-5 (optional).
    self_confidence: Mapped[int | None] = mapped_column(SmallInteger)
    hints_used: Mapped[int] = mapped_column(SmallInteger, server_default="0", default=0)
    score: Mapped[float | None] = mapped_column(Float)
    marked_by: Mapped[str | None] = mapped_column(Enum(*MARKED_BY, name="marked_by"))
    marking_confidence: Mapped[str | None] = mapped_column(Enum(*CONFIDENCE, name="confidence"))
    # Rubric points awarded, feedback, and the explanation of a wrong answer:
    # why, the correct answer, the reasoning, the mistake, how to avoid it.
    feedback: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # From learning.yaml mistakes.categories; the mistake bank (Phase 7) reads it.
    mistake_category: Mapped[str | None] = mapped_column(String(64))
    # The score before a dispute or override, kept for the record.
    original_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[CreatedAt]
    marked_at: Mapped[OptionalTimestamp]

    __table_args__ = (
        ForeignKeyConstraint(
            ["quiz_attempt_id", "user_id"],
            ["quiz_attempts.id", "quiz_attempts.user_id"],
            name="fk_question_attempts_attempt_same_user",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["question_id", "user_id"],
            ["questions.id", "questions.user_id"],
            name="fk_question_attempts_question_same_user",
            ondelete="CASCADE",
        ),
        UniqueConstraint("quiz_attempt_id", "question_id", name="uq_question_attempts_once"),
        CheckConstraint("score IS NULL OR score BETWEEN 0 AND 1", name="score_range"),
        CheckConstraint(
            "self_confidence IS NULL OR self_confidence BETWEEN 1 AND 5", name="confidence_range"
        ),
        Index("ix_question_attempts_user_question", "user_id", "question_id"),
    )
