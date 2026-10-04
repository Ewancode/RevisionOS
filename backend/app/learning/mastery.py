"""Topic strength and difficulty, recomputed from facts (ARCHITECTURE.md
section 10, "Topic strength" and "Difficulty adaptation").

For one module, `recompute` replays every marked answer in time order:

- Elo-style: each topic's ability theta and each question's rating b start
  from their defaults (learning.yaml) and move after every answer, so
  question ratings recalibrate from real outcomes;
- strength: the weighted, smoothed accuracy of the topic's answers (older
  answers count less, harder ones more), blended with the mean FSRS recall
  of its reviewed flashcards.

Because everything is replayed from stored attempts and reviews, the results
are always reproducible and change consistently when a formula changes or a
mark is overridden. Questions with no topic are scored as the module's
"general" bucket (topic_id NULL).
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig
from app.learning import maths, scheduling
from app.models import Flashcard, Question, QuestionAttempt, Topic, TopicMastery

Bucket = uuid.UUID | None
DAY_SECONDS = 86_400


@dataclass
class _Tally:
    ability: float
    evidence: list[maths.Evidence] = field(default_factory=list)
    last: datetime | None = None


async def recompute(
    db: AsyncSession, user_id: uuid.UUID, module_id: uuid.UUID, config: AppConfig, now: datetime
) -> None:
    learning = config.learning
    initial = learning.difficulty.initial_ratings
    questions = {
        q.id: q
        for q in await db.scalars(
            select(Question).where(Question.user_id == user_id, Question.module_id == module_id)
        )
    }
    # Ratings are replayed from their starting values.
    for question in questions.values():
        question.rating = getattr(initial, question.difficulty)

    answers = (
        await db.scalars(
            select(QuestionAttempt)
            .where(
                QuestionAttempt.user_id == user_id,
                QuestionAttempt.question_id.in_(list(questions)),
                QuestionAttempt.score.is_not(None),
                QuestionAttempt.marked_at.is_not(None),
            )
            .order_by(QuestionAttempt.marked_at, QuestionAttempt.id)
        )
    ).all()
    tallies: dict[Bucket, _Tally] = defaultdict(
        lambda: _Tally(ability=learning.difficulty.initial_ability)
    )
    for answer in answers:
        question = questions[answer.question_id]
        score = float(answer.score or 0.0)
        low = answer.marked_by == "ai" and answer.marking_confidence == "low"
        tally = tallies[question.topic_id]
        weight = learning.mastery.low_confidence_mark_weight if low else 1.0
        tally.ability, question.rating = maths.elo_update(
            tally.ability, question.rating, score, learning.difficulty, weight
        )
        marked = answer.marked_at or now  # (the query requires marked_at)
        tally.evidence.append(
            maths.Evidence(
                score=score,
                difficulty=question.difficulty,
                age_days=(now - marked).total_seconds() / DAY_SECONDS,
                low_confidence=low,
            )
        )
        tally.last = max(tally.last, marked) if tally.last else marked

    # Flashcard recall per bucket (cards that have been reviewed).
    recall: dict[Bucket, list[float]] = defaultdict(list)
    for card in await db.scalars(
        select(Flashcard).where(
            Flashcard.user_id == user_id,
            Flashcard.module_id == module_id,
            Flashcard.deleted_at.is_(None),
            Flashcard.last_review.is_not(None),
        )
    ):
        r = scheduling.retrievability(card, now, learning.spaced_repetition)
        if r is not None:
            recall[card.topic_id].append(r)
        if card.last_review:
            tally = tallies[card.topic_id]
            tally.last = max(tally.last, card.last_review) if tally.last else card.last_review

    live_topics = set(
        (
            await db.scalars(
                select(Topic.id).where(
                    Topic.user_id == user_id,
                    Topic.module_id == module_id,
                    Topic.deleted_at.is_(None),
                )
            )
        ).all()
    )
    buckets = {b for b in (*tallies, *recall) if b is None or b in live_topics}
    await db.execute(
        delete(TopicMastery).where(
            TopicMastery.user_id == user_id, TopicMastery.module_id == module_id
        )
    )
    rows = []
    for bucket in buckets:
        tally = tallies[bucket]
        p_hat, weight = maths.smoothed_accuracy(tally.evidence, learning.mastery)
        cards = recall.get(bucket)
        mean_recall = sum(cards) / len(cards) if cards else None
        rows.append(
            {
                "user_id": user_id,
                "module_id": module_id,
                "topic_id": bucket,
                "strength": min(
                    max(maths.strength(p_hat, mean_recall, learning.mastery), 0.0), 1.0
                ),
                "accuracy": p_hat,
                "retrievability": mean_recall,
                "weight": weight,
                "attempts": len(tally.evidence),
                "ability": tally.ability,
                "last_practised_at": tally.last,
                "computed_at": now,
            }
        )
    if rows:
        await db.execute(insert(TopicMastery), rows)
    await db.commit()


async def recompute_for_questions(
    db: AsyncSession,
    user_id: uuid.UUID,
    question_ids: list[uuid.UUID],
    config: AppConfig,
    now: datetime,
) -> None:
    """Recompute every module these questions belong to."""
    modules = set(
        (
            await db.scalars(
                select(Question.module_id).where(
                    Question.id.in_(question_ids), Question.user_id == user_id
                )
            )
        ).all()
    )
    for module_id in modules:
        await recompute(db, user_id, module_id, config, now)
