"""Adaptive learning: progress, flashcard reviews, the daily quiz, the
mistake bank and the learning profile (ARCHITECTURE.md section 10)."""

import uuid
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import Client, Config, CurrentUser, DbSession, rate_limited
from app.learning.daily import DailyPlan
from app.schemas.learning import (
    DailyPlanOut,
    DailyStart,
    DailyStarted,
    DueCard,
    DueCards,
    MistakeGroupOut,
    PlanBucket,
    ProfileOut,
    ProfileSnapshotOut,
    ReviewIn,
    TopicProgress,
    WeakTopic,
)
from app.schemas.practice import FlashcardOut
from app.services.learning import LearningService

router = APIRouter(tags=["learning"])


def _learning(
    request: Request, db: DbSession, user: CurrentUser, client: Client, config: Config
) -> LearningService:
    state = request.app.state
    return LearningService(
        db,
        user.id,
        client,
        config=config,
        jobs=state.jobs,
        embedder=state.embedder,
        claude_available=state.claude.available,
    )


Learning = Annotated[LearningService, Depends(_learning)]


def _plan_out(plan: DailyPlan) -> DailyPlanOut:
    return DailyPlanOut(
        minutes=plan.minutes,
        seconds_per_question=round(plan.seconds_per_question, 1),
        questions=plan.questions,
        buckets=[
            PlanBucket(
                module_id=b.module_id,
                module_code=b.module_code,
                topic_id=b.topic_id,
                title=b.title,
                strength=round(b.strength, 3),
                attempts=b.attempts,
                low_data=b.low_data,
                priority=round(b.priority, 3),
                terms={k: round(v, 3) for k, v in asdict(b.terms).items()},
                available=b.available,
                allocated=b.allocated,
                reasons=b.reasons,
            )
            for b in plan.buckets
        ],
    )


@router.get("/progress", response_model=list[TopicProgress])
async def module_progress(
    module_id: uuid.UUID, learning: Learning, config: Config
) -> list[TopicProgress]:
    """Estimated strength per topic, with its evidence; parents include
    their subtopics, weighted by how much evidence each has."""
    topics, rows = await learning.progress(module_id)
    mastery = config.learning.mastery
    by_topic = {r.topic_id: r for r in rows}
    children: dict[uuid.UUID | None, list[uuid.UUID]] = {}
    for topic in topics:
        children.setdefault(topic.parent_id, []).append(topic.id)

    def subtree(topic_id: uuid.UUID) -> tuple[float, float, int]:
        """(sum of weight * strength, sum of weight, attempts) over the subtree."""
        row = by_topic.get(topic_id)
        weighted = (row.weight * row.strength) if row else 0.0
        weight = row.weight if row else 0.0
        attempts = row.attempts if row else 0
        for child in children.get(topic_id, []):
            w_s, w, n = subtree(child)
            weighted, weight, attempts = weighted + w_s, weight + w, attempts + n
        return weighted, weight, attempts

    out = []
    for topic in topics:
        row = by_topic.get(topic.id)
        weighted, weight, attempts = subtree(topic.id)
        out.append(
            TopicProgress(
                topic_id=topic.id,
                parent_id=topic.parent_id,
                title=topic.title,
                strength=row.strength if row else mastery.prior_accuracy,
                accuracy=row.accuracy if row else mastery.prior_accuracy,
                retrievability=row.retrievability if row else None,
                attempts=row.attempts if row else 0,
                weight=row.weight if row else 0.0,
                low_data=(row.weight if row else 0.0) < mastery.low_data_weight_threshold,
                last_practised_at=row.last_practised_at if row else None,
                subtree_strength=weighted / weight if weight else mastery.prior_accuracy,
                subtree_attempts=attempts,
            )
        )
    general = by_topic.get(None)
    if general is not None:
        out.append(
            TopicProgress(
                topic_id=None,
                parent_id=None,
                title="No topic",
                strength=general.strength,
                accuracy=general.accuracy,
                retrievability=general.retrievability,
                attempts=general.attempts,
                weight=general.weight,
                low_data=general.weight < mastery.low_data_weight_threshold,
                last_practised_at=general.last_practised_at,
                subtree_strength=general.strength,
                subtree_attempts=general.attempts,
            )
        )
    return out


@router.get("/progress/weakest", response_model=list[WeakTopic])
async def weakest_topics(
    learning: Learning, config: Config, limit: Annotated[int, Query(ge=1, le=20)] = 5
) -> list[WeakTopic]:
    """Your weakest topics across this year's modules."""
    threshold = config.learning.mastery.low_data_weight_threshold
    return [
        WeakTopic(
            module_id=row.module_id,
            module_code=code,
            topic_id=row.topic_id,
            title=title,
            strength=row.strength,
            attempts=row.attempts,
            low_data=row.weight < threshold,
            last_practised_at=row.last_practised_at,
        )
        for row, code, title in await learning.weakest(limit)
    ]


@router.get("/flashcards/due", response_model=DueCards)
async def due_flashcards(learning: Learning, module_id: uuid.UUID | None = None) -> DueCards:
    """Cards to review now (new cards limited per day), with the interval
    each rating would give."""
    cards, counts = await learning.due(module_id)
    return DueCards(
        cards=[
            DueCard(
                **FlashcardOut.model_validate(card).model_dump(), intervals=learning.intervals(card)
            )
            for card in cards
        ],
        counts=counts,
    )


@router.post("/flashcards/{card_id}/review", response_model=FlashcardOut)
async def review_flashcard(card_id: uuid.UUID, body: ReviewIn, learning: Learning) -> FlashcardOut:
    """Record how well you knew it: 1 Again, 2 Hard, 3 Good, 4 Easy."""
    return FlashcardOut.model_validate(
        await learning.review(card_id, body.rating, body.duration_ms)
    )


@router.get("/daily-quiz/plan", response_model=DailyPlanOut)
async def daily_plan(
    learning: Learning, minutes: Annotated[int | None, Query(ge=5, le=240)] = None
) -> DailyPlanOut:
    """What today's quiz would cover, and why."""
    return _plan_out(await learning.plan(minutes))


@router.post("/daily-quiz", response_model=DailyStarted, dependencies=[rate_limited("ai")])
async def start_daily_quiz(body: DailyStart, learning: Learning) -> DailyStarted:
    """Start today's quiz (or return the one already open today)."""
    attempt, plan = await learning.start_daily(body.minutes)
    return DailyStarted(attempt_id=attempt.id, plan=_plan_out(plan))


@router.get("/mistakes", response_model=list[MistakeGroupOut])
async def mistakes(learning: Learning, module_id: uuid.UUID | None = None) -> list[MistakeGroupOut]:
    """Your mistakes grouped by topic and kind, recurring ones first."""
    return [
        MistakeGroupOut(
            module_id=g.module_id,
            module_code=g.module_code,
            topic_id=g.topic_id,
            topic_title=g.topic_title,
            category=g.category,
            label=g.label,
            count=g.count,
            recent=g.recent,
            recurring=g.recurring,
            last_at=g.last_at,
            patterns=[asdict(p) for p in g.patterns],
            examples=[asdict(e) for e in g.examples],
        )
        for g in await learning.mistakes(module_id)
    ]


@router.get("/profile", response_model=ProfileOut)
async def learning_profile(learning: Learning) -> ProfileOut:
    """Measured statistics about your learning, and this week's summary."""
    current, snapshot = await learning.profile()
    return ProfileOut(
        current=current,
        snapshot=ProfileSnapshotOut.model_validate(snapshot) if snapshot else None,
    )
