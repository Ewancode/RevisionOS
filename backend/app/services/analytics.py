"""Analytics for one user (SPEC 4, 7, 41, 43): the main and module
dashboards, weekly trends and exam readiness.

The stored events are loaded once per request and handed to the pure
functions in `app.analytics.compute`; every figure carries its basis.
"""

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date, cast, func, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import compute, dashboard
from app.analytics.compute import Answer, Metric, Review, Session
from app.core.clock import utcnow
from app.core.config import AppConfig
from app.learning.mistakes import CATEGORY_LABELS, mistake_bank
from app.models import (
    Document,
    Flashcard,
    FlashcardReview,
    Material,
    Module,
    Question,
    QuestionAttempt,
    Quiz,
    QuizAttempt,
    StudySession,
    TopicMastery,
)
from app.planner import session_builder
from app.planner.context import PlannerContext, available_minutes, load, quiz_minutes
from app.schemas.analytics import (
    DashboardOut,
    DayActivity,
    MetricOut,
    ModuleAnalyticsOut,
    ModuleCard,
    OverviewOut,
    PanelOut,
    ReadinessOut,
    RecentMaterial,
    RecentUpload,
    StreakOut,
    SummaryOut,
    TodayOut,
    TopicStat,
    TrendsOut,
    WeekOut,
)
from app.schemas.planner import BuiltBlock
from app.services.common import ClientInfo, ScopedService


def _out(metric: Metric) -> MetricOut:
    return MetricOut(value=metric.value, basis=metric.basis)


class AnalyticsService(ScopedService):
    def __init__(
        self, db: AsyncSession, user_id: uuid.UUID, client: ClientInfo, *, config: AppConfig
    ) -> None:
        super().__init__(db, user_id, client)
        self.config = config
        self.zone = ZoneInfo(config.ai.budget.timezone)
        self.correct_at = config.practice.marking.correct_at

    # --- loading ------------------------------------------------------------------------------

    async def _events(
        self, module_ids: Sequence[uuid.UUID], since: datetime
    ) -> tuple[list[Answer], list[Review], list[Session]]:
        """Events from `since` on: each view loads only the window it shows,
        not the whole history (Phase 12 performance tests)."""
        answers = [
            Answer(m, t, float(score), at, ms, mistake, kind, attempt)
            for m, t, score, at, ms, mistake, kind, attempt in (
                await self.db.execute(
                    select(
                        Question.module_id,
                        Question.topic_id,
                        QuestionAttempt.score,
                        QuestionAttempt.marked_at,
                        QuestionAttempt.time_ms,
                        QuestionAttempt.mistake_category,
                        Quiz.kind,
                        QuizAttempt.id,
                    )
                    .join(Question, Question.id == QuestionAttempt.question_id)
                    .join(QuizAttempt, QuizAttempt.id == QuestionAttempt.quiz_attempt_id)
                    .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
                    .where(
                        QuestionAttempt.user_id == self.user_id,
                        QuestionAttempt.score.is_not(None),
                        QuestionAttempt.marked_at >= since,
                        Question.module_id.in_(module_ids),
                    )
                )
            ).all()
            if score is not None and at is not None
        ]
        reviews = [
            Review(m, at, ms, rating)
            for m, at, ms, rating in (
                await self.db.execute(
                    select(
                        Flashcard.module_id,
                        FlashcardReview.reviewed_at,
                        FlashcardReview.duration_ms,
                        FlashcardReview.rating,
                    )
                    .join(Flashcard, Flashcard.id == FlashcardReview.flashcard_id)
                    .where(
                        FlashcardReview.user_id == self.user_id,
                        FlashcardReview.reviewed_at >= since,
                        Flashcard.module_id.in_(module_ids),
                    )
                )
            ).all()
        ]
        sessions = [
            Session(m, day, status, minutes)
            for m, day, status, minutes in (
                await self.db.execute(
                    select(
                        StudySession.module_id,
                        StudySession.day,
                        StudySession.status,
                        StudySession.minutes,
                    ).where(
                        StudySession.user_id == self.user_id,
                        StudySession.module_id.in_(module_ids),
                        StudySession.day >= since.astimezone(self.zone).date(),
                    )
                )
            ).all()
        ]
        return answers, reviews, sessions

    async def _active_days(self, module_ids: Sequence[uuid.UUID]) -> set[date]:
        """Every local day with an answer, a review or a completed session,
        as distinct dates from SQL (the streak spans all history)."""
        zone = self.zone.key

        def local(column: Any) -> Any:
            return cast(func.timezone(zone, column), Date)

        answered = (
            select(local(QuestionAttempt.marked_at))
            .join(Question, Question.id == QuestionAttempt.question_id)
            .where(
                QuestionAttempt.user_id == self.user_id,
                QuestionAttempt.score.is_not(None),
                QuestionAttempt.marked_at.is_not(None),
                Question.module_id.in_(module_ids),
            )
        )
        reviewed = (
            select(local(FlashcardReview.reviewed_at))
            .join(Flashcard, Flashcard.id == FlashcardReview.flashcard_id)
            .where(FlashcardReview.user_id == self.user_id, Flashcard.module_id.in_(module_ids))
        )
        done = select(StudySession.day).where(
            StudySession.user_id == self.user_id,
            StudySession.module_id.in_(module_ids),
            StudySession.status == "done",
        )
        return set((await self.db.scalars(union(answered, reviewed, done))).all())

    async def _mastery(self, module_ids: Sequence[uuid.UUID]) -> list[TopicMastery]:
        return list(
            (
                await self.db.scalars(
                    select(TopicMastery).where(
                        TopicMastery.user_id == self.user_id,
                        TopicMastery.module_id.in_(module_ids),
                    )
                )
            ).all()
        )

    # --- shared pieces --------------------------------------------------------------------------

    def _window(self, now: datetime) -> tuple[datetime, str]:
        days = self.config.analytics.windows.recent_days
        start_day = now.astimezone(self.zone).date() - timedelta(days=days - 1)
        start = datetime.combine(start_day, datetime.min.time(), self.zone)
        return start, f"in the last {days} days"

    def _summary(
        self, answers: Sequence[Answer], reviews: Sequence[Review], now: datetime
    ) -> SummaryOut:
        start, label = self._window(now)
        s = compute.summarise(
            [a for a in answers if a.marked_at >= start],
            [r for r in reviews if r.reviewed_at >= start],
            label=label,
            correct_at=self.correct_at,
            config=self.config.analytics,
        )
        return SummaryOut(
            days=self.config.analytics.windows.recent_days,
            answered=_out(s.answered),
            correct=_out(s.correct),
            accuracy=_out(s.accuracy),
            study_minutes=_out(s.study_minutes),
            reviews=_out(s.reviews),
            mistakes=_out(s.mistakes),
        )

    def _module_figures(
        self, ctx: PlannerContext, module_id: uuid.UUID, mastery: Sequence[TopicMastery]
    ) -> tuple[Metric, Metric, Metric]:
        """(progress, coverage, mastered) for one module."""
        rows = [m for m in mastery if m.module_id == module_id]
        weight = sum(m.weight for m in rows)
        answers = sum(m.attempts for m in rows)
        if weight > 0:
            progress = Metric(
                sum(m.weight * m.strength for m in rows) / weight,
                f"Estimated strength of {compute.plural(len(rows), 'topic')} with data, "
                f"weighted by how much recent evidence each has ({answers} answers)",
            )
        else:
            progress = Metric(None, "No marked answers or flashcard reviews in this module yet")
        topics = [t for t in ctx.topics.values() if t.module_id == module_id]
        enough = self.config.learning.daily_quiz.coverage_attempts
        covered = [t for t in topics if t.attempts >= enough]
        coverage = Metric(
            len(covered) / len(topics) if topics else None,
            f"{len(covered)} of {compute.plural(len(topics), 'topic')} with at least "
            f"{enough} marked answers",
        )
        mastered_at = self.config.analytics.topics.mastered_at
        mastered = [t for t in topics if t.strength >= mastered_at and not t.low_data]
        return (
            progress,
            coverage,
            Metric(
                len(mastered),
                f"{len(mastered)} of {compute.plural(len(topics), 'topic')} at an estimated "
                f"{round(mastered_at * 100)}% or more, with enough data",
            ),
        )

    def _topic_stats(self, ctx: PlannerContext) -> tuple[list[TopicStat], list[TopicStat]]:
        cfg = self.config.analytics.topics
        known = [t for t in ctx.topics.values() if not t.low_data]

        def stat(t: object) -> TopicStat:
            return TopicStat.model_validate(t, from_attributes=True)

        strong = sorted(
            (t for t in known if t.strength >= cfg.strong_at), key=lambda t: -t.strength
        )
        weak = sorted((t for t in known if t.strength < cfg.weak_below), key=lambda t: t.strength)
        return [stat(t) for t in strong[: cfg.list_limit]], [
            stat(t) for t in weak[: cfg.list_limit]
        ]

    async def _today(self, ctx: PlannerContext) -> TodayOut:
        sessions = (
            await self.db.scalars(
                select(StudySession).where(
                    StudySession.user_id == self.user_id, StudySession.day == ctx.today
                )
            )
        ).all()
        planned = sum(s.minutes for s in sessions)
        done = sum(s.minutes for s in sessions if s.status == "done")
        parts = [
            f"{sum(1 for s in sessions if s.status == 'done')} of "
            f"{compute.plural(len(sessions), 'planned session')} done ({done} of {planned} min)"
        ]
        quiz = quiz_minutes(ctx, available_minutes(ctx, ctx.today, self.config), self.config)
        if quiz:
            start = datetime.combine(ctx.today, datetime.min.time(), self.zone)
            taken = await self.db.scalar(
                select(func.count())
                .select_from(QuizAttempt)
                .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
                .where(
                    QuizAttempt.user_id == self.user_id,
                    Quiz.kind == "daily",
                    QuizAttempt.submitted_at >= start,
                )
            )
            planned += quiz
            if taken:
                done += quiz
            parts.append(f"daily quiz {'done' if taken else 'not done'} ({quiz} min)")
        progress = (
            Metric(done / planned, "Today: " + "; ".join(parts))
            if planned
            else Metric(None, "Nothing planned today")
        )
        return TodayOut(progress=_out(progress), planned_minutes=planned, done_minutes=done)

    def _readiness(
        self,
        ctx: PlannerContext,
        answers: Sequence[Answer],
        mocks: dict[uuid.UUID, list[float]],
        now: datetime,
    ) -> list[ReadinessOut]:
        cfg = self.config.analytics
        out = []
        for exam in ctx.exams:
            if exam.day < ctx.today:
                continue
            topics = [
                t
                for t in ctx.topics.values()
                if t.module_id == exam.module_id
                and (exam.topic_ids is None or t.topic_id in exam.topic_ids)
            ]
            keys = {t.key for t in topics}
            result = compute.readiness(
                [
                    compute.TopicState(
                        t.topic_id, t.title, t.strength, t.attempts, t.last_practised
                    )
                    for t in topics
                ],
                [a for a in answers if (a.module_id, a.topic_id) in keys],
                mocks.get(exam.module_id, []),
                now=now,
                coverage_attempts=self.config.learning.daily_quiz.coverage_attempts,
                config=cfg.readiness,
            )
            weak = sorted(
                (t for t in topics if t.strength < cfg.topics.weak_below), key=lambda t: t.strength
            )
            out.append(
                ReadinessOut(
                    exam_id=exam.id,
                    module_id=exam.module_id,
                    module_code=exam.module_code,
                    title=exam.title,
                    days_until=(exam.day - ctx.today).days,
                    index=result.index,
                    band=result.band,
                    components={k: _out(m) for k, m in result.components.items()},
                    weak_topics=[
                        TopicStat.model_validate(t, from_attributes=True)
                        for t in weak[: cfg.topics.list_limit]
                    ],
                    note=(
                        "A summary of your preparation so far, from the measurements below. "
                        "It is not a prediction of your mark."
                    ),
                )
            )
        return out

    async def _mock_scores(self, module_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[float]]:
        scores: dict[uuid.UUID, list[float]] = {}
        for module_id, score in (
            await self.db.execute(
                select(Quiz.module_id, QuizAttempt.score)
                .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
                .where(
                    QuizAttempt.user_id == self.user_id,
                    Quiz.kind == "mock",
                    Quiz.module_id.in_(module_ids),
                    QuizAttempt.status == "marked",
                    QuizAttempt.score.is_not(None),
                )
                .order_by(QuizAttempt.marked_at.desc())
            )
        ).all():
            if module_id is not None and score is not None:
                scores.setdefault(module_id, []).append(float(score))
        return scores

    # --- endpoints --------------------------------------------------------------------------------

    async def overview(self) -> OverviewOut:
        now = utcnow()
        ctx = await load(self.db, self.user_id, self.config, now)
        ids = [m.id for m in ctx.modules]
        start, label = self._window(now)
        answers, reviews, _ = await self._events(ids, start)
        mastery = await self._mastery(ids)
        current, longest = compute.streak_metrics(await self._active_days(ids), ctx.today)

        cards = []
        answers_by = compute.by_module(answers)
        for module in ctx.modules:
            progress, coverage, mastered = self._module_figures(ctx, module.id, mastery)
            recent = compute.summarise(
                [a for a in answers_by.get(module.id, []) if a.marked_at >= start],
                [],
                label=label,
                correct_at=self.correct_at,
                config=self.config.analytics,
            )
            cards.append(
                ModuleCard(
                    module_id=module.id,
                    code=module.code,
                    title=module.title,
                    colour=module.colour,
                    progress=_out(progress),
                    coverage=_out(coverage),
                    mastered=_out(mastered),
                    answered=_out(recent.answered),
                    accuracy=_out(recent.accuracy),
                )
            )
        mastered_at = self.config.analytics.topics.mastered_at
        all_topics = list(ctx.topics.values())
        n_mastered = sum(1 for t in all_topics if t.strength >= mastered_at and not t.low_data)
        groups = await mistake_bank(self.db, self.user_id, self.config, now)
        recurring = sum(1 for g in groups if g.recurring)
        strong, weak = self._topic_stats(ctx)
        return OverviewOut(
            today=await self._today(ctx),
            streak=StreakOut(current=_out(current), longest=_out(longest)),
            recent=self._summary(answers, reviews, now),
            mastered=MetricOut(
                value=n_mastered,
                basis=f"{n_mastered} of {compute.plural(len(all_topics), 'topic')} at an "
                f"estimated {round(mastered_at * 100)}% or more, with enough data",
            ),
            mistake_groups=MetricOut(
                value=len(groups),
                basis=f"Mistake-bank groups (by topic and kind of mistake); {recurring} recurring",
            ),
            modules=cards,
            strong=strong,
            weak=weak,
            uploads=await self._uploads(ctx),
            materials=await self._materials(ctx),
        )

    async def _uploads(self, ctx: PlannerContext) -> list[RecentUpload]:
        codes = {m.id: m.code for m in ctx.modules}
        rows = (
            await self.db.scalars(
                select(Document)
                .where(
                    Document.user_id == self.user_id,
                    Document.module_id.in_(codes),
                    Document.deleted_at.is_(None),
                )
                .order_by(Document.created_at.desc())
                .limit(5)
            )
        ).all()
        return [
            RecentUpload(
                id=d.id,
                filename=d.original_filename,
                module_code=codes[d.module_id],
                status=d.status,
                created_at=d.created_at,
            )
            for d in rows
        ]

    async def _materials(self, ctx: PlannerContext) -> list[RecentMaterial]:
        codes = {m.id: m.code for m in ctx.modules}
        rows = (
            await self.db.scalars(
                select(Material)
                .where(
                    Material.user_id == self.user_id,
                    Material.module_id.in_(codes),
                    Material.deleted_at.is_(None),
                )
                .order_by(Material.created_at.desc())
                .limit(5)
            )
        ).all()
        return [
            RecentMaterial(
                id=m.id,
                title=m.title,
                kind=m.kind,
                origin=m.origin,
                module_code=codes[m.module_id],
                created_at=m.created_at,
            )
            for m in rows
        ]

    async def trends(self, module_id: uuid.UUID | None) -> TrendsOut:
        now = utcnow()
        if module_id is not None:
            await self.placement(module_id, None)
            ids: list[uuid.UUID] = [module_id]
            scope = "this module"
        else:
            ids = [
                m.id
                for m in await self.db.scalars(
                    select(Module).where(
                        Module.user_id == self.user_id, Module.deleted_at.is_(None)
                    )
                )
            ]
            scope = "all your modules"
        today = now.astimezone(self.zone).date()
        first_week = compute.week_start(today) - timedelta(
            weeks=self.config.analytics.windows.chart_weeks - 1
        )
        answers, reviews, sessions = await self._events(
            ids, datetime.combine(first_week, datetime.min.time(), self.zone)
        )
        weeks = compute.weekly(
            answers,
            reviews,
            sessions,
            today=today,
            zone=self.zone,
            correct_at=self.correct_at,
            config=self.config.analytics,
        )
        activity = compute.activity_by_day(answers, reviews, sessions, self.zone)
        first = weeks[0].start
        span = (today - first).days + 1
        caps = self.config.analytics.study_time
        return TrendsOut(
            weeks=[
                WeekOut(
                    start=w.start,
                    answered=w.answered,
                    accuracy=w.accuracy,
                    study_minutes=round(w.study_ms / 60_000),
                    reviews=w.reviews,
                    sessions_done=w.sessions_done,
                    sessions_planned=w.sessions_planned,
                    mistakes=dict(w.mistakes),
                )
                for w in weeks
            ],
            days=[
                DayActivity(
                    day=first + timedelta(days=i), events=activity.get(first + timedelta(days=i), 0)
                )
                for i in range(span)
            ],
            mistake_labels=dict(CATEGORY_LABELS),
            basis={
                "accuracy": f"Mean mark of the answers marked each week, in {scope}",
                "study_time": (
                    "Recorded time of each week's answers and flashcard reviews (capped at "
                    f"{caps.answer_cap_minutes} min and {caps.review_cap_seconds} s each), "
                    f"in {scope}"
                ),
                "mistakes": f"Answers with a classified mistake each week, by kind, in {scope}",
                "consistency": (
                    "Days with at least one answer, flashcard review or completed session; "
                    f"and past planned sessions done each week, in {scope}"
                ),
            },
        )

    async def dashboard(self) -> DashboardOut:
        """Today's panels, most pressing first."""
        now = utcnow()
        ctx = await load(self.db, self.user_id, self.config, now)
        upcoming = sorted((e for e in ctx.exams if e.day >= ctx.today), key=lambda e: e.day)
        quiz_done = False
        if ctx.has_questions:
            start = datetime.combine(ctx.today, datetime.min.time(), self.zone)
            quiz_done = bool(
                await self.db.scalar(
                    select(func.count())
                    .select_from(QuizAttempt)
                    .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
                    .where(
                        QuizAttempt.user_id == self.user_id,
                        Quiz.kind == "daily",
                        QuizAttempt.submitted_at >= start,
                    )
                )
            )
        groups = await mistake_bank(self.db, self.user_id, self.config, now)
        pressing = dashboard.Pressing(
            exam_days=(upcoming[0].day - ctx.today).days if upcoming else None,
            exam_title=f"{upcoming[0].module_code} {upcoming[0].title}" if upcoming else "",
            quiz_not_done=ctx.has_questions and not quiz_done,
            cards_due=sum(n for day, n in ctx.due_by_day.items() if day <= ctx.today),
            cards_threshold=self.config.planner.notifications.flashcards_due_threshold,
            recurring_mistakes=sum(1 for g in groups if g.recurring),
        )
        return DashboardOut(
            panels=[
                PanelOut(key=p.key, reason=p.reason)
                for p in dashboard.rank(self.config.analytics.dashboard, pressing)
            ]
        )

    async def readiness(self) -> list[ReadinessOut]:
        now = utcnow()
        ctx = await load(self.db, self.user_id, self.config, now)
        ids = [m.id for m in ctx.modules]
        answers, _, _ = await self._events(ids, self._readiness_since(now))
        return self._readiness(ctx, answers, await self._mock_scores(ids), now)

    def _readiness_since(self, now: datetime) -> datetime:
        return now - timedelta(days=self.config.analytics.readiness.recent_days)

    async def module(self, module_id: uuid.UUID) -> ModuleAnalyticsOut:
        await self.placement(module_id, None)
        now = utcnow()
        ctx = await load(self.db, self.user_id, self.config, now)
        answers, reviews, _ = await self._events(
            [module_id], min(self._window(now)[0], self._readiness_since(now))
        )
        mastery = await self._mastery([module_id])
        progress, coverage, mastered = self._module_figures(ctx, module_id, mastery)
        readiness = self._readiness(ctx, answers, await self._mock_scores([module_id]), now)
        mine = [r for r in readiness if r.module_id == module_id]
        recurring = [
            g
            for g in await mistake_bank(self.db, self.user_id, self.config, now)
            if g.recurring and g.module_id == module_id
        ]
        ctx.topics = {k: t for k, t in ctx.topics.items() if t.module_id == module_id}
        top = session_builder.recommend(ctx, 0, recurring, self.config, limit=1)
        return ModuleAnalyticsOut(
            module_id=module_id,
            progress=_out(progress),
            coverage=_out(coverage),
            mastered=_out(mastered),
            recent=self._summary(answers, reviews, now),
            readiness=mine[0] if mine else None,
            recommendation=BuiltBlock.model_validate(top[0].__dict__) if top else None,
        )
