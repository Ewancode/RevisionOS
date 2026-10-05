"""The revision planner for one user (ARCHITECTURE.md section 11): exams,
availability, preferences, the plan and its sessions, the calendar,
"I have N minutes", and notifications."""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import ClaudeClient
from app.core.clock import utcnow
from app.core.config import AppConfig
from app.core.errors import AppError
from app.learning.mistakes import mistake_bank
from app.models import (
    AvailabilityOverride,
    AvailabilityRule,
    Exam,
    ExamTopic,
    FlashcardReview,
    Module,
    Notification,
    PushSubscription,
    Quiz,
    QuizAttempt,
    StudySession,
    Topic,
    UserSettings,
)
from app.planner import availability, notifications, push, session_builder
from app.planner.context import PlannerContext, available_minutes, load
from app.planner.plan import ensure_fresh, replan
from app.planner.push import Sender
from app.schemas.planner import (
    AvailabilityIn,
    AvailabilityOut,
    AvailabilityProposal,
    CalendarDay,
    CalendarOut,
    ExamIn,
    ExamOut,
    ExamUpdate,
    PlanOut,
    PreferencesIn,
    PreferencesOut,
    PushConfig,
    PushSubscriptionIn,
    StudySessionOut,
)
from app.services.common import ClientInfo, ScopedService, not_found

UPCOMING_DAYS = 14
MAX_CALENDAR_DAYS = 62


class PlannerService(ScopedService):
    def __init__(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        client: ClientInfo,
        *,
        config: AppConfig,
        claude: ClaudeClient | None = None,
    ) -> None:
        super().__init__(db, user_id, client)
        self.config = config
        self.claude = claude
        self.zone = ZoneInfo(config.ai.budget.timezone)

    def _today(self) -> date:
        return utcnow().astimezone(self.zone).date()

    async def _replan(self) -> None:
        await replan(self.db, self.user_id, self.config, utcnow())

    # --- exams ----------------------------------------------------------------------------

    async def _exam(self, exam_id: uuid.UUID) -> Exam:
        exam = await self.db.scalar(
            select(Exam).where(Exam.id == exam_id, Exam.user_id == self.user_id)
        )
        if exam is None:
            raise not_found("exam")
        return exam

    async def exam_out(self, exams: Sequence[Exam]) -> list[ExamOut]:
        codes = {
            m.id: m.code
            for m in await self.db.scalars(
                select(Module).where(Module.id.in_({e.module_id for e in exams}))
            )
        }
        topics: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for exam_id, topic_id in (
            await self.db.execute(
                select(ExamTopic.exam_id, ExamTopic.topic_id).where(
                    ExamTopic.exam_id.in_([e.id for e in exams])
                )
            )
        ).all():
            topics[exam_id].append(topic_id)
        today = self._today()
        return [
            ExamOut(
                id=e.id,
                module_id=e.module_id,
                module_code=codes.get(e.module_id, ""),
                title=e.title,
                starts_at=e.starts_at,
                duration_minutes=e.duration_minutes,
                location=e.location,
                weighting=e.weighting,
                confidence=e.confidence,
                notes=e.notes,
                topic_ids=topics.get(e.id, []),
                days_until=(e.starts_at.astimezone(self.zone).date() - today).days,
            )
            for e in exams
        ]

    async def exams(self, module_id: uuid.UUID | None = None) -> list[ExamOut]:
        stmt = select(Exam).where(Exam.user_id == self.user_id).order_by(Exam.starts_at)
        if module_id is not None:
            await self.placement(module_id, None)
            stmt = stmt.where(Exam.module_id == module_id)
        return await self.exam_out((await self.db.scalars(stmt)).all())

    async def _set_topics(self, exam: Exam, topic_ids: list[uuid.UUID]) -> None:
        await self.db.execute(delete(ExamTopic).where(ExamTopic.exam_id == exam.id))
        for topic_id in dict.fromkeys(topic_ids):
            await self.placement(exam.module_id, topic_id)
            self.db.add(ExamTopic(exam_id=exam.id, topic_id=topic_id, module_id=exam.module_id))

    async def create_exam(self, body: ExamIn) -> ExamOut:
        await self.placement(body.module_id, None)
        exam = Exam(
            id=uuid.uuid4(),
            user_id=self.user_id,
            **body.model_dump(exclude={"topic_ids"}),
        )
        self.db.add(exam)
        await self.db.flush()
        await self._set_topics(exam, body.topic_ids)
        await self.db.commit()
        await self._replan()
        [out] = await self.exam_out([await self._exam(exam.id)])
        return out

    async def update_exam(self, exam_id: uuid.UUID, body: ExamUpdate) -> ExamOut:
        exam = await self._exam(exam_id)
        changes = body.changes()
        topic_ids = changes.pop("topic_ids", None)
        for key, value in changes.items():
            setattr(exam, key, value)
        if topic_ids is not None:
            await self._set_topics(exam, list(topic_ids))  # type: ignore[call-overload]
        await self.db.commit()
        await self._replan()
        [out] = await self.exam_out([await self._exam(exam.id)])
        return out

    async def delete_exam(self, exam_id: uuid.UUID) -> None:
        """Permanent (the UI confirms first); the plan is remade without it."""
        exam = await self._exam(exam_id)
        await self.db.delete(exam)
        self._record("exam_deleted", "exam", exam_id, title=exam.title)
        await self.db.commit()
        await self._replan()

    # --- availability and preferences ----------------------------------------------------

    async def availability(self) -> AvailabilityOut:
        ctx = await load(self.db, self.user_id, self.config, utcnow())
        defaults = self.config.planner.availability
        weekdays = [
            ctx.rules.get(
                d, defaults.default_weekday_minutes if d < 5 else defaults.default_weekend_minutes
            )
            for d in range(7)
        ]
        overrides = (
            await self.db.scalars(
                select(AvailabilityOverride)
                .where(
                    AvailabilityOverride.user_id == self.user_id,
                    AvailabilityOverride.day >= ctx.today,
                )
                .order_by(AvailabilityOverride.day)
            )
        ).all()
        return AvailabilityOut(
            weekdays=weekdays,
            custom=[d in ctx.rules for d in range(7)],
            overrides=[{"day": o.day, "minutes": o.minutes, "note": o.note} for o in overrides],
        )

    async def set_availability(self, body: AvailabilityIn) -> AvailabilityOut:
        for weekday, minutes in enumerate(body.weekdays):
            if minutes is None:
                continue
            await self.db.execute(
                insert(AvailabilityRule)
                .values(user_id=self.user_id, weekday=weekday, minutes=minutes)
                .on_conflict_do_update(
                    index_elements=["user_id", "weekday"], set_={"minutes": minutes}
                )
            )
        for override in body.overrides:
            await self.db.execute(
                insert(AvailabilityOverride)
                .values(
                    user_id=self.user_id,
                    day=override.day,
                    minutes=override.minutes,
                    note=override.note,
                )
                .on_conflict_do_update(
                    index_elements=["user_id", "day"],
                    set_={"minutes": override.minutes, "note": override.note},
                )
            )
        await self.db.commit()
        await self._replan()
        return await self.availability()

    async def delete_override(self, day: date) -> AvailabilityOut:
        result = await self.db.execute(
            delete(AvailabilityOverride).where(
                AvailabilityOverride.user_id == self.user_id, AvailabilityOverride.day == day
            )
        )
        if not result.rowcount:  # type: ignore[attr-defined]
            raise not_found("override")
        await self.db.commit()
        await self._replan()
        return await self.availability()

    async def parse_availability(self, text: str) -> AvailabilityProposal:
        if self.claude is None or not self.claude.available:
            raise AppError(
                "ai_not_configured",
                "Claude is not configured: set the hours directly instead.",
                503,
            )
        proposal = await availability.parse(
            self.db, self.claude, self.config, self.user_id, text, self._today()
        )
        return AvailabilityProposal(
            weekdays=proposal.weekdays,
            dates=[{"day": d, "minutes": m} for d, m in proposal.dates],
            note=proposal.note,
        )

    async def _settings(self) -> UserSettings:
        settings = await self.db.get(UserSettings, self.user_id)
        if settings is None:
            settings = UserSettings(user_id=self.user_id)
            self.db.add(settings)
            await self.db.flush()
        return settings

    async def preferences(self) -> PreferencesOut:
        settings = await self._settings()
        defaults = self.config.planner
        return PreferencesOut(
            session_minutes=settings.session_minutes or defaults.allocation.session_minutes,
            max_sessions_per_day=settings.max_sessions_per_day
            or defaults.allocation.max_sessions_per_day,
            rest_weekdays=sorted(settings.rest_weekdays or []),
            notify_exams=settings.notify_exams,
            notify_quiz=settings.notify_quiz,
            notify_neglected=settings.notify_neglected,
            notify_flashcards=settings.notify_flashcards,
            quiz_reminder_hour=settings.quiz_reminder_hour
            if settings.quiz_reminder_hour is not None
            else defaults.notifications.quiz_reminder_hour,
            quiet_from=settings.quiet_from,
            quiet_to=settings.quiet_to,
        )

    async def set_preferences(self, body: PreferencesIn) -> PreferencesOut:
        settings = await self._settings()
        changes = body.changes()
        for key, value in changes.items():
            if key == "rest_weekdays":
                value = sorted(set(value or []))  # type: ignore[call-overload]
            setattr(settings, key, value)
        await self.db.commit()
        if {"session_minutes", "max_sessions_per_day", "rest_weekdays"} & changes.keys():
            await self._replan()
        return await self.preferences()

    # --- the plan and its sessions -----------------------------------------------------------

    async def _titles(self, sessions: Sequence[StudySession]) -> dict[uuid.UUID | None, str]:
        topic_ids = {s.topic_id for s in sessions if s.topic_id}
        titles: dict[uuid.UUID | None, str] = {
            t.id: t.title
            for t in await self.db.scalars(select(Topic).where(Topic.id.in_(topic_ids)))
        }
        return titles

    async def session_out(self, sessions: Sequence[StudySession]) -> list[StudySessionOut]:
        titles = await self._titles(sessions)
        codes = {
            m.id: m.code
            for m in await self.db.scalars(
                select(Module).where(Module.id.in_({s.module_id for s in sessions}))
            )
        }
        out = []
        for s in sessions:
            code = codes.get(s.module_id, "")
            title = (
                f"{code} mock exam"
                if s.kind == "mock_exam"
                else titles.get(s.topic_id, f"{code}, whole module")
            )
            out.append(
                StudySessionOut(
                    id=s.id,
                    module_id=s.module_id,
                    module_code=code,
                    topic_id=s.topic_id,
                    title=title,
                    exam_id=s.exam_id,
                    kind=s.kind,
                    day=s.day,
                    minutes=s.minutes,
                    status=s.status,
                    locked=s.locked,
                    actual_minutes=s.actual_minutes,
                    reason=s.reason,
                )
            )
        return out

    async def _sessions(self, start: date, end: date) -> Sequence[StudySession]:
        return (
            await self.db.scalars(
                select(StudySession)
                .where(
                    StudySession.user_id == self.user_id,
                    StudySession.day >= start,
                    StudySession.day <= end,
                )
                .order_by(StudySession.day, StudySession.kind.desc(), StudySession.created_at)
            )
        ).all()

    async def plan(self) -> PlanOut:
        plan = await ensure_fresh(self.db, self.user_id, self.config, utcnow())
        today = self._today()
        sessions = await self.session_out(
            await self._sessions(today, today + timedelta(days=UPCOMING_DAYS))
        )
        upcoming = [e for e in await self.exams() if e.days_until >= 0]
        return PlanOut(
            generated_at=plan.generated_at,
            starts=date.fromisoformat(plan.params.get("from", today.isoformat())),
            ends=date.fromisoformat(plan.params.get("to", today.isoformat())),
            shortfalls=plan.shortfalls,
            today=[s for s in sessions if s.day == today],
            upcoming=[s for s in sessions if s.day > today],
            exams=upcoming,
        )

    async def _session(self, session_id: uuid.UUID) -> StudySession:
        session = await self.db.scalar(
            select(StudySession).where(
                StudySession.id == session_id, StudySession.user_id == self.user_id
            )
        )
        if session is None:
            raise not_found("session")
        return session

    async def move(self, session_id: uuid.UUID, day: date, minutes: int | None) -> StudySessionOut:
        """Move (or resize) a session: it is locked there, and the rest of the
        plan rebalances around it."""
        session = await self._session(session_id)
        if day < self._today():
            raise AppError("in_the_past", "Sessions can only move to today or later.", 422)
        session.day = day
        if minutes is not None:
            session.minutes = minutes
        session.locked = True
        await self.db.commit()
        await self._replan()
        [out] = await self.session_out([await self._session(session_id)])
        return out

    async def set_status(
        self, session_id: uuid.UUID, status: str, actual_minutes: int | None
    ) -> StudySessionOut:
        session = await self._session(session_id)
        session.status = status
        if status == "done":
            session.actual_minutes = actual_minutes or session.minutes
            session.completed_at = utcnow()
        elif status == "planned":
            session.actual_minutes, session.completed_at = None, None
        await self.db.commit()
        await self._replan()
        [out] = await self.session_out([await self._session(session_id)])
        return out

    # --- calendar ------------------------------------------------------------------------------

    async def calendar(self, start: date, end: date) -> CalendarOut:
        if end < start or (end - start).days >= MAX_CALENDAR_DAYS:
            raise AppError("bad_range", f"Show at most {MAX_CALENDAR_DAYS} days at a time.", 422)
        await ensure_fresh(self.db, self.user_id, self.config, utcnow())
        ctx = await load(self.db, self.user_id, self.config, utcnow())
        sessions = await self.session_out(await self._sessions(start, end))
        exams = await self.exams()
        quizzes: dict[date, list[dict[str, Any]]] = defaultdict(list)
        for attempt, quiz in (
            await self.db.execute(
                select(QuizAttempt, Quiz)
                .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
                .where(QuizAttempt.user_id == self.user_id)
            )
        ).all():
            day = attempt.started_at.astimezone(self.zone).date()
            if start <= day <= end:
                quizzes[day].append(
                    {
                        "attempt_id": str(attempt.id),
                        "title": quiz.title,
                        "kind": quiz.kind,
                        "status": attempt.status,
                        "score": attempt.score,
                    }
                )
        reviews: dict[date, int] = defaultdict(int)
        for at in (
            await self.db.scalars(
                select(FlashcardReview.reviewed_at).where(FlashcardReview.user_id == self.user_id)
            )
        ).all():
            reviews[at.astimezone(self.zone).date()] += 1
        days = []
        for i in range((end - start).days + 1):
            day = start + timedelta(days=i)
            days.append(
                CalendarDay(
                    day=day,
                    available_minutes=available_minutes(ctx, day, self.config),
                    sessions=[s for s in sessions if s.day == day],
                    exams=[e for e in exams if e.starts_at.astimezone(self.zone).date() == day],
                    quizzes=quizzes.get(day, []),
                    reviews=reviews.get(day, 0),
                    due_cards=ctx.due_by_day.get(day, 0) if day >= ctx.today else 0,
                )
            )
        return CalendarOut(start=start, end=end, days=days)

    # --- "I have N minutes" and notifications ---------------------------------------------------

    async def context(self) -> PlannerContext:
        return await load(self.db, self.user_id, self.config, utcnow())

    async def build_session(self, minutes: int) -> session_builder.SessionPlan:
        limits = self.config.planner.session_builder
        if not limits.min_minutes <= minutes <= limits.max_minutes:
            raise AppError(
                "bad_minutes",
                f"Choose between {limits.min_minutes} and {limits.max_minutes} minutes.",
                422,
            )
        now = utcnow()
        ctx = await load(self.db, self.user_id, self.config, now)
        recurring = [
            g for g in await mistake_bank(self.db, self.user_id, self.config, now) if g.recurring
        ]
        due = sum(n for day, n in ctx.due_by_day.items() if day <= ctx.today)
        return session_builder.build(ctx, minutes, due, recurring, self.config)

    async def recommendations(self, limit: int) -> list[session_builder.Block]:
        now = utcnow()
        ctx = await load(self.db, self.user_id, self.config, now)
        recurring = [
            g for g in await mistake_bank(self.db, self.user_id, self.config, now) if g.recurring
        ]
        due = sum(n for day, n in ctx.due_by_day.items() if day <= ctx.today)
        return session_builder.recommend(ctx, due, recurring, self.config, limit)

    # --- push -----------------------------------------------------------------------------------

    async def push_config(self, public_key: str | None, enabled: bool) -> PushConfig:
        devices = await self.db.scalar(
            select(func.count())
            .select_from(PushSubscription)
            .where(PushSubscription.user_id == self.user_id)
        )
        return PushConfig(
            enabled=enabled, public_key=public_key if enabled else None, devices=int(devices or 0)
        )

    async def subscribe(self, body: PushSubscriptionIn) -> None:
        """Register this device. The same browser signed in as someone else
        moves to them: a device belongs to one account."""
        if not push.is_push_service(body.endpoint, self.config.planner.notifications.push_hosts):
            raise AppError("not_push_service", "That is not a browser push service.", 422)
        stmt = insert(PushSubscription).values(
            id=uuid.uuid4(),
            user_id=self.user_id,
            endpoint=body.endpoint,
            p256dh=body.keys.p256dh,
            auth=body.keys.auth,
            label=body.label,
        )
        await self.db.execute(
            stmt.on_conflict_do_update(
                index_elements=[PushSubscription.endpoint],
                set_={
                    "user_id": self.user_id,
                    "p256dh": body.keys.p256dh,
                    "auth": body.keys.auth,
                    "label": body.label,
                    "failures": 0,
                },
            )
        )
        await self.db.commit()

    async def unsubscribe(self, endpoint: str) -> None:
        await self.db.execute(
            delete(PushSubscription).where(
                PushSubscription.user_id == self.user_id, PushSubscription.endpoint == endpoint
            )
        )
        await self.db.commit()

    async def test_push(self, sender: Sender | None) -> int:
        if sender is None:
            raise AppError("push_off", "Push is not set up on the server (make vapid-keys).", 409)
        devices = (
            await self.db.scalars(
                select(PushSubscription).where(PushSubscription.user_id == self.user_id)
            )
        ).all()
        if not devices:
            raise AppError("no_devices", "Turn on notifications on this device first.", 409)
        note = Notification(
            user_id=self.user_id,
            kind="test",
            title="Notifications are working.",
            body="Revision OS will remind you here about exams, quizzes and due cards.",
            link="/settings",
            dedupe_key=f"test:{uuid.uuid4()}",
            read_at=utcnow(),
        )
        self.db.add(note)
        await self.db.flush()
        return await push.deliver(self.db, sender, self.config, devices, [note], utcnow())

    async def notifications(self) -> tuple[int, Sequence[Notification]]:
        now = utcnow()
        ctx = await load(self.db, self.user_id, self.config, now)
        await notifications.refresh(self.db, self.user_id, ctx, self.config, now)
        items = (
            await self.db.scalars(
                select(Notification)
                .where(Notification.user_id == self.user_id)
                .order_by(Notification.read_at.is_not(None), Notification.created_at.desc())
                .limit(50)
            )
        ).all()
        unread = await self.db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == self.user_id, Notification.read_at.is_(None))
        )
        return int(unread or 0), items

    async def read(self, notification_id: int | None) -> None:
        stmt = update(Notification).where(
            Notification.user_id == self.user_id, Notification.read_at.is_(None)
        )
        if notification_id is not None:
            exists = await self.db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.id == notification_id, Notification.user_id == self.user_id)
            )
            if not exists:
                raise not_found("notification")
            stmt = stmt.where(Notification.id == notification_id)
        await self.db.execute(stmt.values(read_at=utcnow()))
        await self.db.commit()
