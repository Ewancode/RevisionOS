"""Making and keeping the plan (ARCHITECTURE.md section 11, "Rebalancing").

`replan` keeps the past, your locked sessions and anything already done,
marks past sessions you did not do as missed, and recomputes every future,
unlocked session. It runs when exams, availability, preferences or sessions
change, and lazily whenever the plan is out of date (a new day, or new
results since it was made), which covers both "after a quiz" and "nightly".
"""

import uuid
from dataclasses import asdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig
from app.models import RevisionPlan, StudySession, TopicMastery
from app.planner import allocator
from app.planner.context import PlannerContext, capacity, horizon, load, needs


def _reason(ctx: PlannerContext, item: allocator.Planned) -> str:
    if item.kind == "mock_exam":
        exam = next((e for e in ctx.exams if e.id == item.exam_id), None)
        if exam is None:
            return "Mock exam"
        days = (exam.day - item.day).days
        return f"Mock exam under timed conditions, {days} days before {exam.title}"
    topic = ctx.topics.get((item.module_id, item.topic_id))
    return topic.factors(ctx.today, ctx.now) if topic else ""


async def replan(
    db: AsyncSession, user_id: uuid.UUID, config: AppConfig, now: datetime
) -> RevisionPlan:
    ctx = await load(db, user_id, config, now)
    # Yesterday's undone sessions were missed.
    await db.execute(
        update(StudySession)
        .where(
            StudySession.user_id == user_id,
            StudySession.day < ctx.today,
            StudySession.status == "planned",
        )
        .values(status="missed")
    )
    # Future, unlocked plans are recomputed; the rest stays.
    await db.execute(
        delete(StudySession).where(
            StudySession.user_id == user_id,
            StudySession.day >= ctx.today,
            StudySession.status == "planned",
            StudySession.locked.is_(False),
        )
    )
    kept = (
        await db.scalars(
            select(StudySession).where(
                StudySession.user_id == user_id, StudySession.day >= ctx.today
            )
        )
    ).all()
    end = horizon(ctx, config)
    span = (end - ctx.today).days + 1
    days = [
        allocator.Day(d, capacity(ctx, d, config))
        for d in (ctx.today + timedelta(days=i) for i in range(span))
    ]
    locked = [
        allocator.Locked(s.day, s.actual_minutes or s.minutes, s.module_id, s.topic_id)
        for s in kept
        if s.status != "skipped"
    ]
    exams = [
        allocator.ExamSlot(e.id, e.module_id, e.day, e.duration_minutes, e.title)
        for e in ctx.exams
        if e.day > ctx.today and not any(s.kind == "mock_exam" and s.exam_id == e.id for s in kept)
    ]
    planned, shortfalls = allocator.allocate(
        days,
        needs(ctx, config, span),
        locked,
        exams,
        config.planner.allocation,
        session_minutes=ctx.preferences.session_minutes,
        max_sessions=ctx.preferences.max_sessions_per_day,
    )
    plan = RevisionPlan(
        id=uuid.uuid4(),
        user_id=user_id,
        generated_at=now,
        params={
            "from": ctx.today.isoformat(),
            "to": end.isoformat(),
            "exams": len(ctx.exams),
            "topics": len(ctx.topics),
            "available_minutes": sum(d.capacity for d in days),
            "session_minutes": ctx.preferences.session_minutes,
        },
        shortfalls=[{**asdict(s), "exam_id": str(s.exam_id)} for s in shortfalls],
    )
    db.add(plan)
    await db.flush()
    for item in planned:
        db.add(
            StudySession(
                id=uuid.uuid4(),
                user_id=user_id,
                plan_id=plan.id,
                module_id=item.module_id,
                topic_id=item.topic_id,
                exam_id=item.exam_id,
                kind=item.kind,
                day=item.day,
                minutes=item.minutes,
                reason=_reason(ctx, item),
            )
        )
    await db.commit()
    return plan


async def current(db: AsyncSession, user_id: uuid.UUID) -> RevisionPlan | None:
    return await db.scalar(
        select(RevisionPlan)
        .where(RevisionPlan.user_id == user_id)
        .order_by(RevisionPlan.generated_at.desc())
        .limit(1)
    )


async def ensure_fresh(
    db: AsyncSession, user_id: uuid.UUID, config: AppConfig, now: datetime
) -> RevisionPlan:
    """The current plan, remade first if a day has passed (in your timezone)
    or results have changed since it was made."""
    zone = ZoneInfo(config.ai.budget.timezone)
    plan = await current(db, user_id)
    if plan is not None:
        newest = await db.scalar(
            select(func.max(TopicMastery.computed_at)).where(TopicMastery.user_id == user_id)
        )
        same_day = plan.generated_at.astimezone(zone).date() == now.astimezone(zone).date()
        if same_day and (newest is None or newest <= plan.generated_at):
            return plan
    return await replan(db, user_id, config, now)
