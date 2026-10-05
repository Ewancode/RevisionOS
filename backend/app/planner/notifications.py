"""In-app reminders (SPEC 44; ARCHITECTURE.md section 11, "Notifications").

Made when you open the app (each one only once, by a dedupe key), so no
background scheduler is needed for in-app use:

- an exam in 14, 7 and 1 days;
- today's quiz not done by your reminder hour;
- a topic with an exam in view not practised for N days;
- many flashcards due.

Each kind can be switched off, and quiet hours hold back new reminders.
Browser push arrives with the PWA (Phase 11).
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig
from app.models import Notification, Quiz, QuizAttempt, UserSettings
from app.planner.context import DAY_SECONDS, PlannerContext


def is_quiet(settings: UserSettings | None, hour: int) -> bool:
    if settings is None or settings.quiet_from is None or settings.quiet_to is None:
        return False
    start, end = settings.quiet_from, settings.quiet_to
    return start <= hour < end if start < end else hour >= start or hour < end


async def refresh(
    db: AsyncSession, user_id: uuid.UUID, ctx: PlannerContext, config: AppConfig, now: datetime
) -> None:
    settings = await db.get(UserSettings, user_id)
    rules = config.planner.notifications
    local = now.astimezone(ctx.zone)
    if is_quiet(settings, local.hour):
        return
    wanted: list[dict[str, object]] = []

    def add(kind: str, key: str, title: str, body: str = "", link: str | None = None) -> None:
        wanted.append(
            {
                "user_id": user_id,
                "kind": kind,
                "dedupe_key": key,
                "title": title,
                "body": body,
                "link": link,
            }
        )

    if settings is None or settings.notify_exams:
        for exam in ctx.exams:
            days = (exam.day - ctx.today).days
            if days in rules.exam_days:
                when = "tomorrow" if days == 1 else f"in {days} days"
                add(
                    "exam",
                    f"exam:{exam.id}:{days}",
                    f"Your {exam.module_code} exam is {when}.",
                    f"{exam.title}, {exam.starts_at.astimezone(ctx.zone):%a %d %b %H:%M}.",
                    "/planner",
                )

    reminder = (settings.quiz_reminder_hour if settings else None) or rules.quiz_reminder_hour
    if (settings is None or settings.notify_quiz) and local.hour >= reminder and ctx.has_questions:
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        done = await db.scalar(
            select(func.count())
            .select_from(QuizAttempt)
            .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
            .where(
                QuizAttempt.user_id == user_id,
                Quiz.kind == "daily",
                QuizAttempt.submitted_at >= start,
            )
        )
        if not done:
            add("quiz", f"quiz:{ctx.today}", "You haven't completed today's quiz.", link="/")

    if settings is None or settings.notify_neglected:
        for topic in ctx.topics.values():
            if topic.exam is None or topic.last_practised is None:
                continue
            days = int((now - topic.last_practised).total_seconds() // DAY_SECONDS)
            if days >= rules.neglected_days:
                add(
                    "neglected",
                    f"neglected:{topic.module_id}:{topic.topic_id}:{topic.last_practised.date()}",
                    f"You haven't reviewed {topic.title} for {days} days.",
                    topic.factors(ctx.today, now),
                    "/planner",
                )

    due = ctx.due_by_day.get(ctx.today, 0)
    if (settings is None or settings.notify_flashcards) and due >= rules.flashcards_due_threshold:
        add(
            "flashcards",
            f"flashcards:{ctx.today}",
            f"You have {due} flashcards due today.",
            link="/review",
        )

    if wanted:
        await db.execute(insert(Notification).values(wanted).on_conflict_do_nothing())
    await db.execute(
        delete(Notification).where(
            Notification.user_id == user_id,
            Notification.read_at < now - timedelta(days=rules.keep_days),
        )
    )
    await db.commit()
