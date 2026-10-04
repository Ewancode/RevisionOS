"""The mistake bank (SPEC 27; ARCHITECTURE.md section 10, "Mistake bank").

Every wrong answer that was explained carries a category from learning.yaml
and a one-line description of the mistake. Mistakes are grouped by topic and
category; a group is *recurring* when it has at least `recurring_min_count`
mistakes within `recurring_window_days`. Within a group, near-identical
descriptions (by embedding similarity) are shown as one pattern with a count.
Recurring patterns are what the daily quiz deliberately targets.
"""

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig
from app.models import Module, Question, QuestionAttempt, Topic
from app.retrieval.embeddings import EmbeddingProvider

CATEGORY_LABELS = {
    "arithmetic_or_algebra_slip": "Arithmetic or algebra slip",
    "sign_error": "Sign error",
    "wrong_method": "Wrong tool or method",
    "concept_confusion": "Concept confusion",
    "incomplete_justification": "Incomplete justification",
    "instance_instead_of_general": "Instance instead of a general argument",
    "notation": "Notation",
}


@dataclass
class Example:
    answer_id: uuid.UUID
    attempt_id: uuid.UUID
    question_id: uuid.UUID
    stem_md: str
    at: datetime
    description: str


@dataclass
class Pattern:
    description: str
    count: int


@dataclass
class MistakeGroup:
    module_id: uuid.UUID
    module_code: str
    topic_id: uuid.UUID | None
    topic_title: str
    category: str
    count: int = 0
    recent: int = 0
    recurring: bool = False
    last_at: datetime | None = None
    patterns: list[Pattern] = field(default_factory=list)
    examples: list[Example] = field(default_factory=list)

    @property
    def label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category.replace("_", " ").capitalize())


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


async def _patterns(
    descriptions: list[str], embedder: EmbeddingProvider, threshold: float
) -> list[Pattern]:
    texts = [d for d in descriptions if d.strip()]
    if not texts:
        return []
    vectors = await embedder.embed_passages(texts)
    clusters: list[tuple[list[float], Pattern]] = []
    for text, vector in zip(texts, vectors, strict=True):
        for centre, pattern in clusters:
            if _cosine(vector, centre) >= threshold:
                pattern.count += 1
                break
        else:
            clusters.append((vector, Pattern(text, 1)))
    return sorted((p for _, p in clusters), key=lambda p: -p.count)


async def mistake_bank(
    db: AsyncSession,
    user_id: uuid.UUID,
    config: AppConfig,
    now: datetime,
    embedder: EmbeddingProvider | None = None,
    module_id: uuid.UUID | None = None,
) -> list[MistakeGroup]:
    settings = config.learning.mistakes
    correct_at = config.practice.marking.correct_at
    stmt = (
        select(QuestionAttempt, Question, Module.code, Topic.title)
        .join(Question, Question.id == QuestionAttempt.question_id)
        .join(Module, Module.id == Question.module_id)
        .outerjoin(Topic, Topic.id == Question.topic_id)
        .where(
            QuestionAttempt.user_id == user_id,
            QuestionAttempt.mistake_category.is_not(None),
            QuestionAttempt.score < correct_at,
            Module.deleted_at.is_(None),
        )
        .order_by(QuestionAttempt.marked_at.desc())
    )
    if module_id is not None:
        stmt = stmt.where(Question.module_id == module_id)
    window_start = now - timedelta(days=settings.recurring_window_days)
    groups: dict[tuple[uuid.UUID | None, str], MistakeGroup] = {}
    descriptions: dict[tuple[uuid.UUID | None, str], list[str]] = {}
    for answer, question, code, topic_title in (await db.execute(stmt)).all():
        key = (question.topic_id, str(answer.mistake_category))
        group = groups.setdefault(
            key,
            MistakeGroup(
                module_id=question.module_id,
                module_code=code,
                topic_id=question.topic_id,
                topic_title=topic_title or f"{code} (no topic)",
                category=str(answer.mistake_category),
            ),
        )
        at = answer.marked_at or answer.created_at
        group.count += 1
        if at >= window_start:
            group.recent += 1
        group.last_at = max(group.last_at, at) if group.last_at else at
        description = str(((answer.feedback or {}).get("explanation") or {}).get("mistake", ""))
        descriptions.setdefault(key, []).append(description)
        if len(group.examples) < 5:
            group.examples.append(
                Example(
                    answer_id=answer.id,
                    attempt_id=answer.quiz_attempt_id,
                    question_id=question.id,
                    stem_md=question.stem_md,
                    at=at,
                    description=description,
                )
            )
    for key, group in groups.items():
        group.recurring = group.recent >= settings.recurring_min_count
        if embedder is not None:
            group.patterns = await _patterns(
                descriptions[key], embedder, settings.description_similarity
            )
    return sorted(
        groups.values(),
        key=lambda g: (not g.recurring, -g.recent, -g.count),
    )
