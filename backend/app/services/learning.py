"""Adaptive learning for one user: topic strengths, flashcard reviews, the
daily quiz, the mistake bank and the learning profile (ARCHITECTURE.md
section 10)."""

import random
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.budget import BudgetGuard
from app.core.clock import utcnow
from app.core.config import AppConfig
from app.core.errors import AppError
from app.learning import daily, mastery, profile, scheduling
from app.learning.mistakes import MistakeGroup, mistake_bank
from app.models import (
    Draft,
    Flashcard,
    FlashcardReview,
    LearningProfileSnapshot,
    Module,
    Quiz,
    QuizAttempt,
    Topic,
    TopicMastery,
)
from app.retrieval.embeddings import EmbeddingProvider
from app.services.common import ClientInfo, ScopedService, not_found
from app.services.quizzes import QuizService, ensure_no_exam
from app.workers.queue import JobQueue


class LearningService(ScopedService):
    def __init__(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        client: ClientInfo,
        *,
        config: AppConfig,
        jobs: JobQueue,
        embedder: EmbeddingProvider | None = None,
        claude_available: bool = False,
    ) -> None:
        super().__init__(db, user_id, client)
        self.config = config
        self.jobs = jobs
        self.embedder = embedder
        self.claude_available = claude_available

    # --- topic strength ---------------------------------------------------------------

    async def progress(self, module_id: uuid.UUID) -> tuple[list[Topic], list[TopicMastery]]:
        await self.placement(module_id, None)
        topics = (
            await self.db.scalars(
                select(Topic)
                .where(
                    Topic.user_id == self.user_id,
                    Topic.module_id == module_id,
                    Topic.deleted_at.is_(None),
                )
                .order_by(Topic.position)
            )
        ).all()
        rows = (
            await self.db.scalars(
                select(TopicMastery).where(
                    TopicMastery.user_id == self.user_id, TopicMastery.module_id == module_id
                )
            )
        ).all()
        return list(topics), list(rows)

    async def weakest(self, limit: int) -> list[tuple[TopicMastery, str, str]]:
        """Your weakest topics with evidence, across current modules."""
        modules = await daily.current_modules(self.db, self.user_id)
        rows = (
            await self.db.execute(
                select(TopicMastery, Module.code, Topic.title)
                .join(Module, Module.id == TopicMastery.module_id)
                .outerjoin(Topic, Topic.id == TopicMastery.topic_id)
                .where(
                    TopicMastery.user_id == self.user_id,
                    TopicMastery.module_id.in_([m.id for m in modules]),
                    TopicMastery.attempts > 0,
                )
                .order_by(TopicMastery.strength)
                .limit(limit)
            )
        ).all()
        return [(row, code, title or f"{code} (no topic)") for row, code, title in rows]

    # --- flashcards ----------------------------------------------------------------------

    async def due(
        self, module_id: uuid.UUID | None, limit: int = 50
    ) -> tuple[list[Flashcard], dict[str, int]]:
        """Cards due now, oldest due first, with new cards limited per day."""
        now = utcnow()
        stmt = select(Flashcard).where(
            Flashcard.user_id == self.user_id,
            Flashcard.deleted_at.is_(None),
            Flashcard.due <= now,
        )
        if module_id is not None:
            await self.placement(module_id, None)
            stmt = stmt.where(Flashcard.module_id == module_id)
        cards = list((await self.db.scalars(stmt.order_by(Flashcard.due))).all())
        new_today = await self.db.scalar(
            select(func.count())
            .select_from(FlashcardReview)
            .where(
                FlashcardReview.user_id == self.user_id,
                FlashcardReview.elapsed_days.is_(None),
                FlashcardReview.reviewed_at >= self._day_start(now),
            )
        )
        allowance = max(
            0, self.config.learning.spaced_repetition.new_cards_per_day - (new_today or 0)
        )
        seen = [c for c in cards if c.reps > 0]
        fresh = [c for c in cards if c.reps == 0][:allowance]
        counts = {
            "due": len(seen) + len(fresh),
            "review": sum(1 for c in seen if c.fsrs_state == 2),
            "learning": sum(1 for c in seen if c.fsrs_state != 2),
            "new": len(fresh),
        }
        return (seen + fresh)[:limit], counts

    def _day_start(self, now: datetime) -> datetime:
        zone = ZoneInfo(self.config.ai.budget.timezone)
        local = now.astimezone(zone)
        return local.replace(hour=0, minute=0, second=0, microsecond=0)

    def intervals(self, card: Flashcard) -> dict[int, float]:
        return scheduling.preview(card, utcnow(), self.config.learning.spaced_repetition)

    async def review(self, card_id: uuid.UUID, rating: int, duration_ms: int | None) -> Flashcard:
        card = await self.db.scalar(
            select(Flashcard).where(
                Flashcard.id == card_id,
                Flashcard.user_id == self.user_id,
                Flashcard.deleted_at.is_(None),
            )
        )
        if card is None:
            raise not_found("flashcard")
        now = utcnow()
        self.db.add(
            scheduling.review(
                card, rating, now, self.config.learning.spaced_repetition, duration_ms
            )
        )
        await self.db.commit()
        await mastery.recompute(self.db, self.user_id, card.module_id, self.config, now)
        await self.db.refresh(card)
        return card

    # --- the daily quiz ----------------------------------------------------------------------

    async def plan(self, minutes: int | None) -> daily.DailyPlan:
        return await daily.plan(self.db, self.user_id, self.config, utcnow(), minutes)

    async def _open_daily(self, now: datetime) -> QuizAttempt | None:
        return await self.db.scalar(
            select(QuizAttempt)
            .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
            .where(
                QuizAttempt.user_id == self.user_id,
                Quiz.kind == "daily",
                QuizAttempt.status == "in_progress",
                QuizAttempt.started_at >= self._day_start(now),
            )
        )

    async def start_daily(
        self, minutes: int | None, rng: random.Random | None = None
    ) -> tuple[QuizAttempt, daily.DailyPlan]:
        """Today's quiz: the one already open, or a new one."""
        await ensure_no_exam(self.db, self.user_id, self.config, self.jobs)
        now = utcnow()
        plan = await self.plan(minutes)
        open_ = await self._open_daily(now)
        if open_ is not None:
            return open_, plan
        questions = await daily.choose(
            self.db,
            self.user_id,
            self.config,
            now,
            plan,
            rng or random.Random(),  # noqa: S311
        )
        await self._top_up(plan, now)
        if not questions:
            raise AppError(
                "no_questions",
                "There are no questions to practise yet. Generate some from your materials.",
                422,
            )
        local = now.astimezone(ZoneInfo(self.config.ai.budget.timezone))
        quizzes = QuizService(
            self.db, self.user_id, self.client, config=self.config, jobs=self.jobs
        )
        _, attempt = await quizzes.create_from(
            questions,
            kind="daily",
            title=f"Daily quiz, {local.day} {local:%B}",
            module_id=None,
            config={"minutes": plan.minutes, "planned": plan.questions},
        )
        return attempt, plan

    async def _top_up(self, plan: daily.DailyPlan, now: datetime) -> None:
        """Ask Claude for questions in high-priority topics that have too few
        (auto-saved once they pass the checks). Off if the AI budget is near
        its limit, Claude is not configured, or today's allowance is used."""
        settings = self.config.learning.daily_quiz.top_up
        if not (settings.enabled and settings.max_topics_per_day and self.claude_available):
            return
        status = await BudgetGuard(self.db, self.user_id, self.config.ai.budget).status()
        if status.warning:
            return
        today = self._day_start(now)
        started = await self.db.scalar(
            select(func.count())
            .select_from(Draft)
            .where(
                Draft.user_id == self.user_id,
                Draft.created_at >= today,
                Draft.request["auto"].as_boolean().is_(True),
            )
        )
        room = settings.max_topics_per_day - (started or 0)
        thin = [
            b
            for b in plan.buckets
            if b.topic_id is not None and b.total_questions < settings.min_questions_per_topic
        ]
        if room <= 0 or not thin:
            return
        # Imported here: drafts -> quizzes -> marking -> learning.
        from app.schemas.practice import GenerateRequest
        from app.services.drafts import DraftService

        drafts = DraftService(
            self.db, self.user_id, self.client, config=self.config, jobs=self.jobs
        )
        for bucket in thin[:room]:
            await drafts.create(
                GenerateRequest(
                    module_id=bucket.module_id,
                    topic_id=bucket.topic_id,
                    kind="questions",
                    count=settings.generate,
                    difficulty="mixed",
                ),
                auto=True,
            )

    # --- mistakes and profile -------------------------------------------------------------------

    async def mistakes(self, module_id: uuid.UUID | None) -> list[MistakeGroup]:
        if module_id is not None:
            await self.placement(module_id, None)
        return await mistake_bank(
            self.db, self.user_id, self.config, utcnow(), self.embedder, module_id
        )

    async def profile(self) -> tuple[dict[str, Any], LearningProfileSnapshot | None]:
        """Current measurements, and this week's snapshot (made on first view
        each week, with Claude's summary written in the background)."""
        now = utcnow()
        current = await profile.metrics(self.db, self.user_id, self.config, now)
        week = profile.week_start(now.astimezone(ZoneInfo(self.config.ai.budget.timezone)).date())
        snapshot = await self.db.scalar(
            select(LearningProfileSnapshot)
            .where(LearningProfileSnapshot.user_id == self.user_id)
            .order_by(LearningProfileSnapshot.week_start.desc())
            .limit(1)
        )
        settings = self.config.learning.profile
        stale = snapshot is None or snapshot.week_start <= week - timedelta(
            days=settings.refresh_days
        )
        if stale and int(current.get("answered") or 0) >= settings.min_answers:
            snapshot = LearningProfileSnapshot(
                user_id=self.user_id, week_start=week, metrics=current, computed_at=now
            )
            self.db.add(snapshot)
            await self.db.commit()
            await self.db.refresh(snapshot)
            if self.claude_available:
                await self.jobs.enqueue(
                    "summarise_profile", snapshot.id, job_id=f"profile:{snapshot.id}"
                )
        return current, snapshot
