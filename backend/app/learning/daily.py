"""Choosing the daily quiz (SPEC 21; ARCHITECTURE.md section 10, "Daily quiz
selection").

1. Every topic in your current modules gets a priority from five terms in
   [0, 1] (weights in learning.yaml):
   weakness (1 - strength), overdue (days since practised), urgency (exam
   proximity, from Phase 8), recurring (a recurring mistake there) and gap
   (few answers yet). With no data every topic scores the same, so the
   first quizzes spread evenly, as SPEC 21 asks.
2. Length: your available minutes divided by your median time per question,
   clamped.
3. Questions are shared out in proportion to priority, with a floor per
   module, and never more than a topic has available.
4. Within a topic, questions aimed at a recurring mistake come first; then
   those whose predicted success (Elo) is nearest the 65-80% target band.
   Questions answered right in the last few days are skipped.
5. The order interleaves modules and question types.
"""

import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig
from app.learning import maths
from app.learning.mistakes import CATEGORY_LABELS, MistakeGroup, mistake_bank
from app.models import AcademicYear, Module, Question, QuestionAttempt, Topic, TopicMastery

DAY_SECONDS = 86_400
Key = tuple[uuid.UUID, uuid.UUID | None]  # (module, topic or None)


@dataclass
class BucketPlan:
    module_id: uuid.UUID
    module_code: str
    topic_id: uuid.UUID | None
    title: str
    strength: float
    attempts: int
    low_data: bool
    ability: float
    terms: maths.PriorityTerms
    priority: float
    available: int
    total_questions: int
    allocated: int = 0
    reasons: list[str] = field(default_factory=list)
    recurring: list[MistakeGroup] = field(default_factory=list)

    @property
    def key(self) -> Key:
        return (self.module_id, self.topic_id)


@dataclass
class DailyPlan:
    minutes: int
    seconds_per_question: float
    questions: int
    buckets: list[BucketPlan]

    @property
    def chosen(self) -> list[BucketPlan]:
        return [b for b in self.buckets if b.allocated]


async def current_modules(db: AsyncSession, user_id: uuid.UUID) -> list[Module]:
    """Active modules of the current academic year (or all active ones)."""
    year = await db.scalar(
        select(AcademicYear.id).where(
            AcademicYear.user_id == user_id, AcademicYear.is_current.is_(True)
        )
    )
    stmt = select(Module).where(
        Module.user_id == user_id, Module.deleted_at.is_(None), Module.status == "active"
    )
    if year is not None:
        stmt = stmt.where(Module.academic_year_id == year)
    return list((await db.scalars(stmt.order_by(Module.code))).all())


async def _seconds_per_question(db: AsyncSession, user_id: uuid.UUID, default: int) -> float:
    times = (
        await db.scalars(
            select(QuestionAttempt.time_ms)
            .where(QuestionAttempt.user_id == user_id, QuestionAttempt.time_ms > 0)
            .order_by(QuestionAttempt.created_at.desc())
            .limit(50)
        )
    ).all()
    found = maths.median([t / 1000 for t in times if t])
    return found if found else float(default)


async def plan(
    db: AsyncSession,
    user_id: uuid.UUID,
    config: AppConfig,
    now: datetime,
    minutes: int | None = None,
) -> DailyPlan:
    settings = config.learning.daily_quiz
    mastery_config = config.learning.mastery
    modules = await current_modules(db, user_id)
    module_ids = [m.id for m in modules]
    codes = {m.id: m.code for m in modules}
    minutes = minutes or settings.default_minutes
    seconds = await _seconds_per_question(db, user_id, settings.default_seconds_per_question)
    count = round(minutes * 60 / seconds)
    count = min(max(count, settings.min_questions), settings.max_questions)
    if not modules:
        return DailyPlan(minutes, seconds, 0, [])

    topics = (
        await db.scalars(
            select(Topic).where(
                Topic.user_id == user_id,
                Topic.module_id.in_(module_ids),
                Topic.deleted_at.is_(None),
            )
        )
    ).all()
    mastery = {
        (m.module_id, m.topic_id): m
        for m in await db.scalars(
            select(TopicMastery).where(
                TopicMastery.user_id == user_id, TopicMastery.module_id.in_(module_ids)
            )
        )
    }
    totals = {
        (module_id, topic_id): n
        for module_id, topic_id, n in (
            await db.execute(
                select(Question.module_id, Question.topic_id, func.count())
                .where(
                    Question.user_id == user_id,
                    Question.module_id.in_(module_ids),
                    Question.status == "active",
                )
                .group_by(Question.module_id, Question.topic_id)
            )
        ).all()
    }
    available = await _available(db, user_id, module_ids, config, now)
    recurring: dict[Key, list[MistakeGroup]] = {}
    for group in await mistake_bank(db, user_id, config, now):
        if group.recurring and group.module_id in codes:
            recurring.setdefault((group.module_id, group.topic_id), []).append(group)

    keys: list[tuple[Key, str]] = [((t.module_id, t.id), t.title) for t in topics]
    for module in modules:
        if totals.get((module.id, None)):
            keys.append(((module.id, None), f"{module.code} (no topic)"))

    buckets = []
    for key, title in keys:
        row = mastery.get(key)
        strength = row.strength if row else mastery_config.prior_accuracy
        attempts = row.attempts if row else 0
        days_since = (
            (now - row.last_practised_at).total_seconds() / DAY_SECONDS
            if row and row.last_practised_at
            else None
        )
        groups = recurring.get(key, [])
        terms = maths.PriorityTerms(
            weakness=1 - strength,
            overdue=maths.overdue(days_since, settings.overdue_after_days),
            urgency=0.0,  # exams arrive in Phase 8
            recurring=1.0 if groups else 0.0,
            gap=maths.coverage_gap(attempts, settings.coverage_attempts),
        )
        reasons = []
        if attempts:
            reasons.append(f"est. {round(strength * 100)}% strength")
        if days_since is None:
            reasons.append("not practised yet")
        elif days_since >= settings.overdue_after_days / 2:
            reasons.append(f"not practised for {int(days_since)} days")
        reasons += [
            f"recurring {CATEGORY_LABELS.get(g.category, g.category).lower()}" for g in groups
        ]
        buckets.append(
            BucketPlan(
                module_id=key[0],
                module_code=codes[key[0]],
                topic_id=key[1],
                title=title,
                strength=strength,
                attempts=attempts,
                low_data=(row.weight if row else 0.0) < mastery_config.low_data_weight_threshold,
                ability=row.ability if row else config.learning.difficulty.initial_ability,
                terms=terms,
                priority=terms.total(settings.weights),
                available=len(available.get(key, [])),
                total_questions=totals.get(key, 0),
                reasons=reasons,
                recurring=groups,
            )
        )

    shares = maths.allocate(
        count,
        {b.key: b.priority for b in buckets},
        {b.key: b.available for b in buckets},
        groups={b.key: str(b.module_id) for b in buckets},
        group_floor=settings.module_floor,
    )
    for bucket in buckets:
        bucket.allocated = shares.get(bucket.key, 0)
    buckets.sort(key=lambda b: -b.priority)
    return DailyPlan(minutes, seconds, sum(shares.values()), buckets)


async def _available(
    db: AsyncSession,
    user_id: uuid.UUID,
    module_ids: list[uuid.UUID],
    config: AppConfig,
    now: datetime,
) -> dict[Key, list[Question]]:
    """Active questions per bucket, minus those answered right very recently."""
    since = now - timedelta(days=config.learning.daily_quiz.avoid_repeat_days)
    recent_right = set(
        (
            await db.scalars(
                select(QuestionAttempt.question_id).where(
                    QuestionAttempt.user_id == user_id,
                    QuestionAttempt.marked_at >= since,
                    QuestionAttempt.score >= config.practice.marking.correct_at,
                )
            )
        ).all()
    )
    found: dict[Key, list[Question]] = {}
    for question in await db.scalars(
        select(Question).where(
            Question.user_id == user_id,
            Question.module_id.in_(module_ids),
            Question.status == "active",
        )
    ):
        if question.id not in recent_right:
            found.setdefault((question.module_id, question.topic_id), []).append(question)
    return found


async def choose(
    db: AsyncSession,
    user_id: uuid.UUID,
    config: AppConfig,
    now: datetime,
    daily: DailyPlan,
    rng: random.Random,
) -> list[Question]:
    """The questions for a plan, in quiz order."""
    settings = config.learning
    pool = await _available(db, user_id, [b.module_id for b in daily.chosen], config, now)
    targets_left = settings.daily_quiz.recurring_targets
    wrong_with: dict[uuid.UUID, set[str]] = {}
    for question_id, category in (
        await db.execute(
            select(QuestionAttempt.question_id, QuestionAttempt.mistake_category).where(
                QuestionAttempt.user_id == user_id,
                QuestionAttempt.mistake_category.is_not(None),
            )
        )
    ).all():
        wrong_with.setdefault(question_id, set()).add(str(category))

    picked: list[list[Question]] = []
    for bucket in sorted(daily.chosen, key=lambda b: -b.priority):
        candidates = list(pool.get(bucket.key, []))
        rng.shuffle(candidates)  # ties broken at random
        categories = {g.category for g in bucket.recurring}
        chosen: list[Question] = []
        if categories and targets_left:
            aimed = [q for q in candidates if wrong_with.get(q.id, set()) & categories]
            for question in aimed[: min(targets_left, bucket.allocated)]:
                chosen.append(question)
                targets_left -= 1
        rest = sorted(
            (q for q in candidates if q not in chosen),
            key=lambda q: maths.target_distance(bucket.ability, q.rating, settings.difficulty),
        )
        chosen += rest[: bucket.allocated - len(chosen)]
        picked.append(chosen)
    return _interleave(picked)


def _interleave(groups: list[list[Question]]) -> list[Question]:
    """Round-robin over topics, avoiding the same type twice in a row where
    possible."""
    queues = [list(g) for g in groups if g]
    order: list[Question] = []
    while any(queues):
        for queue in queues:
            if not queue:
                continue
            previous = order[-1].type if order else None
            index = next((i for i, q in enumerate(queue) if q.type != previous), 0)
            order.append(queue.pop(index))
    return order
