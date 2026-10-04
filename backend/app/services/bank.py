"""A module's question bank and flashcards (SPEC 26 and 29)."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import AppConfig
from app.learning import mastery
from app.models import Flashcard, Question, QuestionAttempt
from app.retrieval.embeddings import EmbeddingProvider
from app.schemas.practice import (
    FlashcardCreate,
    FlashcardUpdate,
    QuestionOut,
    QuestionUpdate,
)
from app.services.common import ClientInfo, ScopedService, not_found


@dataclass(frozen=True)
class History:
    attempts: int
    last_score: float | None
    last_at: datetime | None


@dataclass(frozen=True)
class BankFilters:
    topic_ids: Sequence[uuid.UUID] | None = None
    difficulties: Sequence[str] | None = None
    types: Sequence[str] | None = None
    # any | unattempted | wrong | right
    result: str = "any"
    origin: str | None = None
    status: str = "active"


class QuestionService(ScopedService):
    def __init__(
        self, db: AsyncSession, user_id: uuid.UUID, client: ClientInfo, *, config: AppConfig
    ) -> None:
        super().__init__(db, user_id, client)
        self.config = config

    async def get(self, question_id: uuid.UUID) -> Question:
        question = await self.db.scalar(
            select(Question).where(Question.id == question_id, Question.user_id == self.user_id)
        )
        if question is None:
            raise not_found("question")
        return question

    async def history(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, History]:
        """Marked attempts per question: how many, and the latest result."""
        if not ids:
            return {}
        rows = (
            await self.db.execute(
                select(
                    QuestionAttempt.question_id, QuestionAttempt.score, QuestionAttempt.marked_at
                )
                .where(
                    QuestionAttempt.user_id == self.user_id,
                    QuestionAttempt.question_id.in_(ids),
                    QuestionAttempt.score.is_not(None),
                )
                .order_by(QuestionAttempt.marked_at)
            )
        ).all()
        found: dict[uuid.UUID, History] = {}
        for question_id, score, at in rows:
            seen = found.get(question_id)
            found[question_id] = History((seen.attempts if seen else 0) + 1, score, at)
        return found

    def _matches(self, history: History | None, result: str) -> bool:
        correct = self.config.practice.marking.correct_at
        if result == "unattempted":
            return history is None
        if result == "wrong":
            return history is not None and (history.last_score or 0.0) < correct
        if result == "right":
            return history is not None and (history.last_score or 0.0) >= correct
        return True

    async def bank(self, module_id: uuid.UUID, filters: BankFilters) -> list[QuestionOut]:
        await self.placement(module_id, None)
        stmt = select(Question).where(
            Question.user_id == self.user_id,
            Question.module_id == module_id,
            Question.status == filters.status,
        )
        if filters.topic_ids:
            stmt = stmt.where(Question.topic_id.in_(filters.topic_ids))
        if filters.difficulties:
            stmt = stmt.where(Question.difficulty.in_(filters.difficulties))
        if filters.types:
            stmt = stmt.where(Question.type.in_(filters.types))
        if filters.origin:
            stmt = stmt.where(Question.origin == filters.origin)
        questions = (await self.db.scalars(stmt.order_by(Question.created_at.desc()))).all()
        history = await self.history([q.id for q in questions])
        out = []
        for question in questions:
            seen = history.get(question.id)
            if not self._matches(seen, filters.result):
                continue
            out.append(
                QuestionOut.model_validate(question).model_copy(
                    update={
                        "attempts": seen.attempts if seen else 0,
                        "last_score": seen.last_score if seen else None,
                        "last_attempted_at": seen.last_at if seen else None,
                    }
                )
            )
        return out

    async def update(self, question_id: uuid.UUID, body: QuestionUpdate) -> Question:
        question = await self.get(question_id)
        changes = body.changes()
        if "topic_id" in changes:
            await self.placement(question.module_id, body.topic_id)
        if body.difficulty is not None and body.difficulty != question.difficulty:
            ratings = self.config.learning.difficulty.initial_ratings
            question.rating = getattr(ratings, body.difficulty)
        for key, value in changes.items():
            setattr(question, key, value)
        await self.db.commit()
        if {"topic_id", "difficulty"} & changes.keys():
            await mastery.recompute(
                self.db, self.user_id, question.module_id, self.config, utcnow()
            )
        return question


class FlashcardService(ScopedService):
    def __init__(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        client: ClientInfo,
        *,
        embedder: EmbeddingProvider,
    ) -> None:
        super().__init__(db, user_id, client)
        self.embedder = embedder

    async def get(self, card_id: uuid.UUID) -> Flashcard:
        card = await self.db.scalar(
            select(Flashcard).where(
                Flashcard.id == card_id,
                Flashcard.user_id == self.user_id,
                Flashcard.deleted_at.is_(None),
            )
        )
        if card is None:
            raise not_found("flashcard")
        return card

    async def list(self, module_id: uuid.UUID, topic_id: uuid.UUID | None) -> Sequence[Flashcard]:
        await self.placement(module_id, None)
        stmt = select(Flashcard).where(
            Flashcard.user_id == self.user_id,
            Flashcard.module_id == module_id,
            Flashcard.deleted_at.is_(None),
        )
        if topic_id is not None:
            stmt = stmt.where(Flashcard.topic_id == topic_id)
        return (await self.db.scalars(stmt.order_by(Flashcard.created_at))).all()

    async def create(self, body: FlashcardCreate) -> Flashcard:
        await self.placement(body.module_id, body.topic_id)
        [vector] = await self.embedder.embed_passages([body.front_md])
        card = Flashcard(
            id=uuid.uuid4(),
            user_id=self.user_id,
            module_id=body.module_id,
            topic_id=body.topic_id,
            front_md=body.front_md,
            back_md=body.back_md,
            origin="user",
            embedding=vector,
        )
        self.db.add(card)
        await self.db.commit()
        await self.db.refresh(card)
        return card

    async def update(self, card_id: uuid.UUID, body: FlashcardUpdate) -> Flashcard:
        card = await self.get(card_id)
        changes = body.changes()
        if "topic_id" in changes:
            await self.placement(card.module_id, body.topic_id)
        for key, value in changes.items():
            setattr(card, key, value)
        if "front_md" in changes:
            [card.embedding] = await self.embedder.embed_passages([card.front_md])
        await self.db.commit()
        await self.db.refresh(card)
        return card

    async def delete(self, card_id: uuid.UUID) -> None:
        card = await self.get(card_id)
        card.deleted_at = utcnow()
        self._record("flashcard_deleted", "flashcard", card.id)
        await self.db.commit()

    async def restore(self, card_id: uuid.UUID, since: timedelta) -> Flashcard:
        card = await self.db.scalar(
            select(Flashcard).where(
                Flashcard.id == card_id,
                Flashcard.user_id == self.user_id,
                Flashcard.deleted_at >= utcnow() - since,
            )
        )
        if card is None:
            raise not_found("flashcard")
        card.deleted_at = None
        await self.db.commit()
        await self.db.refresh(card)
        return card
