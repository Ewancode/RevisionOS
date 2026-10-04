"""Everything the planner needs, loaded once: exams, topics with their
evidence, availability, reserves and preferences (ARCHITECTURE.md section 11,
"Inputs")."""

import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig
from app.learning import maths as learning_maths
from app.learning.daily import current_modules
from app.models import (
    AvailabilityOverride,
    AvailabilityRule,
    Exam,
    ExamTopic,
    Flashcard,
    Module,
    Question,
    QuestionAttempt,
    Topic,
    TopicMastery,
    UserSettings,
)
from app.planner.allocator import Key, TopicNeed, urgency

DAY_SECONDS = 86_400


@dataclass(frozen=True)
class ExamInfo:
    id: uuid.UUID
    module_id: uuid.UUID
    module_code: str
    title: str
    starts_at: datetime
    day: date  # local
    duration_minutes: int
    weighting: int | None
    confidence: int | None
    # None: the whole module.
    topic_ids: frozenset[uuid.UUID] | None


@dataclass
class TopicInfo:
    module_id: uuid.UUID
    module_code: str
    topic_id: uuid.UUID | None
    title: str
    strength: float
    attempts: int
    low_data: bool
    last_practised: datetime | None
    mistakes_30d: int = 0
    exam: ExamInfo | None = None
    importance: int = 3  # 1-5, from the topic tree

    @property
    def key(self) -> Key:
        return (self.module_id, self.topic_id)

    def factors(self, today: date, now: datetime) -> str:
        """The engine's real numbers, e.g. "est. 43% · 4 mistakes in 30 days ·
        last practised 6 days ago · exam in 34 days"."""
        parts = [f"est. {round(self.strength * 100)}%"]
        if self.low_data:
            parts.append("little data yet")
        if self.importance != 3:
            parts.append(f"importance {self.importance}/5")
        if self.mistakes_30d:
            parts.append(
                f"{self.mistakes_30d} mistake{'s' if self.mistakes_30d != 1 else ''} in 30 days"
            )
        if self.last_practised is None:
            parts.append("not practised yet")
        else:
            days = int((now - self.last_practised).total_seconds() // DAY_SECONDS)
            parts.append(
                "practised today"
                if days == 0
                else f"last practised {days} day{'s' if days != 1 else ''} ago"
            )
        if self.exam is not None:
            days = (self.exam.day - today).days
            parts.append(
                f"{self.exam.module_code} exam {'tomorrow' if days == 1 else f'in {days} days'}"
            )
        return " · ".join(parts)


@dataclass
class Preferences:
    session_minutes: int
    max_sessions_per_day: int
    rest_weekdays: frozenset[int]


@dataclass
class PlannerContext:
    now: datetime
    zone: ZoneInfo
    today: date
    modules: list[Module]
    exams: list[ExamInfo]
    topics: dict[Key, TopicInfo]
    preferences: Preferences
    rules: dict[int, int]
    overrides: dict[date, int]
    due_by_day: dict[date, int]
    has_questions: bool
    flags: dict[str, bool] = field(default_factory=dict)

    def local(self, at: datetime) -> date:
        return at.astimezone(self.zone).date()


async def load(
    db: AsyncSession, user_id: uuid.UUID, config: AppConfig, now: datetime
) -> PlannerContext:
    zone = ZoneInfo(config.ai.budget.timezone)
    today = now.astimezone(zone).date()
    modules = await current_modules(db, user_id)
    module_ids = [m.id for m in modules]
    codes = {m.id: m.code for m in modules}
    mastery_config = config.learning.mastery

    settings = await db.get(UserSettings, user_id)
    allocation = config.planner.allocation
    preferences = Preferences(
        session_minutes=(settings.session_minutes if settings else None)
        or allocation.session_minutes,
        max_sessions_per_day=(settings.max_sessions_per_day if settings else None)
        or allocation.max_sessions_per_day,
        rest_weekdays=frozenset(settings.rest_weekdays if settings else []),
    )

    exam_rows = (
        await db.scalars(
            select(Exam)
            .where(Exam.user_id == user_id, Exam.module_id.in_(module_ids))
            .order_by(Exam.starts_at)
        )
    ).all()
    covered: dict[uuid.UUID, set[uuid.UUID]] = {}
    for exam_id, topic_id in (
        await db.execute(
            select(ExamTopic.exam_id, ExamTopic.topic_id).where(
                ExamTopic.exam_id.in_([e.id for e in exam_rows])
            )
        )
    ).all():
        covered.setdefault(exam_id, set()).add(topic_id)
    exams = [
        ExamInfo(
            id=e.id,
            module_id=e.module_id,
            module_code=codes[e.module_id],
            title=e.title,
            starts_at=e.starts_at,
            day=e.starts_at.astimezone(zone).date(),
            duration_minutes=e.duration_minutes,
            weighting=e.weighting,
            confidence=e.confidence,
            topic_ids=frozenset(covered[e.id]) if e.id in covered else None,
        )
        for e in exam_rows
    ]
    upcoming = [e for e in exams if e.day >= today]

    topic_rows = (
        await db.scalars(
            select(Topic)
            .where(
                Topic.user_id == user_id,
                Topic.module_id.in_(module_ids),
                Topic.deleted_at.is_(None),
            )
            .order_by(Topic.position)
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
    keys: list[tuple[Key, str]] = [((t.module_id, t.id), t.title) for t in topic_rows]
    importance = {t.id: t.importance for t in topic_rows}
    with_topics = {t.module_id for t in topic_rows}
    for module in modules:
        if module.id not in with_topics:
            keys.append(((module.id, None), f"{module.code}, whole module"))

    mistakes = {
        (module_id, topic_id): n
        for module_id, topic_id, n in (
            await db.execute(
                select(Question.module_id, Question.topic_id, func.count())
                .join(QuestionAttempt, QuestionAttempt.question_id == Question.id)
                .where(
                    Question.user_id == user_id,
                    Question.module_id.in_(module_ids),
                    QuestionAttempt.mistake_category.is_not(None),
                    QuestionAttempt.marked_at >= now - timedelta(days=30),
                )
                .group_by(Question.module_id, Question.topic_id)
            )
        ).all()
    }
    topics: dict[Key, TopicInfo] = {}
    for key, title in keys:
        row = mastery.get(key)
        exam = next(
            (
                e
                for e in upcoming
                if e.module_id == key[0] and (e.topic_ids is None or key[1] in e.topic_ids)
            ),
            None,
        )
        topics[key] = TopicInfo(
            module_id=key[0],
            module_code=codes[key[0]],
            topic_id=key[1],
            title=title,
            strength=row.strength if row else mastery_config.prior_accuracy,
            attempts=row.attempts if row else 0,
            low_data=(row.weight if row else 0.0) < mastery_config.low_data_weight_threshold,
            last_practised=row.last_practised_at if row else None,
            mistakes_30d=mistakes.get(key, 0),
            exam=exam,
            importance=importance.get(key[1], 3) if key[1] else 3,
        )

    rules = {
        r.weekday: r.minutes
        for r in await db.scalars(
            select(AvailabilityRule).where(AvailabilityRule.user_id == user_id)
        )
    }
    overrides = {
        o.day: o.minutes
        for o in await db.scalars(
            select(AvailabilityOverride).where(
                AvailabilityOverride.user_id == user_id, AvailabilityOverride.day >= today
            )
        )
    }
    due_by_day: dict[date, int] = {}
    for due in (
        await db.scalars(
            select(Flashcard.due).where(
                Flashcard.user_id == user_id,
                Flashcard.module_id.in_(module_ids),
                Flashcard.deleted_at.is_(None),
            )
        )
    ).all():
        day = max(due.astimezone(zone).date(), today)
        due_by_day[day] = due_by_day.get(day, 0) + 1
    has_questions = bool(
        await db.scalar(
            select(func.count())
            .select_from(Question)
            .where(Question.user_id == user_id, Question.module_id.in_(module_ids))
        )
    )
    return PlannerContext(
        now=now,
        zone=zone,
        today=today,
        modules=list(modules),
        exams=exams,
        topics=topics,
        preferences=preferences,
        rules=rules,
        overrides=overrides,
        due_by_day=due_by_day,
        has_questions=has_questions,
    )


# --- time ----------------------------------------------------------------------------


def available_minutes(ctx: PlannerContext, day: date, config: AppConfig) -> int:
    settings = config.planner.availability
    if day in ctx.overrides:
        minutes = ctx.overrides[day]
    elif day.weekday() in ctx.preferences.rest_weekdays:
        minutes = 0
    elif day.weekday() in ctx.rules:
        minutes = ctx.rules[day.weekday()]
    else:
        minutes = (
            settings.default_weekday_minutes
            if day.weekday() < 5
            else settings.default_weekend_minutes
        )
    return min(minutes, settings.max_minutes_per_day)


def quiz_minutes(ctx: PlannerContext, available: int, config: AppConfig) -> int:
    """Time kept for the daily quiz: a share of the day, within limits."""
    reserve = config.planner.reserve
    if not ctx.has_questions or available <= 0:
        return 0
    minutes = round(available * reserve.daily_quiz_fraction)
    return min(
        max(minutes, reserve.daily_quiz_min_minutes), reserve.daily_quiz_max_minutes, available
    )


def flashcard_minutes(ctx: PlannerContext, day: date, config: AppConfig) -> int:
    reserve = config.planner.reserve
    cards = ctx.due_by_day.get(day, 0)
    return min(math.ceil(cards * reserve.flashcard_seconds / 60), reserve.flashcard_max_minutes)


def capacity(ctx: PlannerContext, day: date, config: AppConfig) -> int:
    available = available_minutes(ctx, day, config)
    reserved = quiz_minutes(ctx, available, config) + flashcard_minutes(ctx, day, config)
    return max(0, available - reserved)


def horizon(ctx: PlannerContext, config: AppConfig) -> date:
    allocation = config.planner.allocation
    latest = max((e.day for e in ctx.exams if e.day >= ctx.today), default=None)
    end = latest or ctx.today + timedelta(days=allocation.horizon_days_without_exams - 1)
    return min(end, ctx.today + timedelta(days=allocation.max_horizon_days))


# --- need ------------------------------------------------------------------------------


def needs(ctx: PlannerContext, config: AppConfig, days: int) -> list[TopicNeed]:
    """Minutes each topic needs before its exam (or light upkeep)."""
    allocation = config.planner.allocation
    coverage = config.learning.daily_quiz.coverage_attempts
    found = []
    for topic in ctx.topics.values():
        gap = learning_maths.coverage_gap(topic.attempts, coverage)
        weakness = 1 - topic.strength
        importance = 1 + allocation.importance_step * (topic.importance - 3)
        if topic.exam is not None:
            exam = topic.exam
            weight = (exam.weighting or 100) / 100
            confidence = (
                1 + allocation.confidence_step * (3 - exam.confidence) if exam.confidence else 1.0
            )
            minutes = (
                allocation.need_scale_minutes
                * weight
                * weakness
                * (1 + allocation.coverage_bonus * gap)
                * confidence
                * importance
            )
            found.append(
                TopicNeed(
                    topic.module_id, topic.topic_id, topic.title, round(minutes), exam.id, exam.day
                )
            )
        else:
            minutes = allocation.maintenance_minutes * (days / 14) * weakness * 2 * importance
            found.append(
                TopicNeed(
                    topic.module_id,
                    topic.topic_id,
                    topic.title,
                    round(minutes),
                    priority_factor=allocation.maintenance_priority,
                )
            )
    return found


def priority_now(
    topic: TopicInfo, need: TopicNeed, ctx: PlannerContext, config: AppConfig
) -> float:
    """The allocator's priority for today (for "I have N minutes")."""
    days_to = (topic.exam.day - ctx.today).days if topic.exam else None
    return (
        need.need_minutes
        / config.planner.allocation.need_scale_minutes
        * urgency(days_to, config.planner.allocation.urgency_half_days)
        * need.priority_factor
    )


def exam_urgency(ctx: PlannerContext, config: AppConfig) -> dict[Key, float]:
    """The daily quiz's urgency term, from each topic's next exam."""
    half = config.planner.allocation.urgency_half_days
    return {
        key: urgency((t.exam.day - ctx.today).days, half)
        for key, t in ctx.topics.items()
        if t.exam is not None
    }
