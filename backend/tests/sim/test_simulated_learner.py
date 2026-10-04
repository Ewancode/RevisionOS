"""The simulated learner: Phase 7's acceptance test (ARCHITECTURE.md section 13,
"Adaptive behaviour").

A learner with a known, fixed chance of answering right in each of three
topics (strong 90%, medium 60%, weak 25%) takes a daily quiz for two weeks.
The system is never told those numbers. It must:

- start with an even spread (no data yet);
- move practice towards the weak topic and away from the strong one;
- rank the topics' estimated strength in the true order;
- predict success on the weak topic close to the truth (Elo ability is
  fitted jointly with each topic's question ratings, so it is compared via
  predicted success, not across topics directly).
"""

import json
import random
import uuid
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import ClaudeClient
from app.core import clock
from app.core.config import get_config
from app.learning import maths
from app.models import Question, QuestionAttempt, QuizAttempt, TopicMastery
from app.practice.marking import mark_attempt
from app.services.common import ClientInfo
from app.services.learning import LearningService
from app.services.quizzes import submit_attempt
from tests.fakes import FakeAnthropic, RecordingQueue
from tests.learning_support import make_module, make_questions
from tests.support import make_user

pytestmark = pytest.mark.db

TRUE_SKILL = {"Strong": 0.9, "Medium": 0.6, "Weak": 0.25}
DAYS = 14
START = datetime(2026, 10, 5, 9, tzinfo=UTC)


@pytest.fixture
def frozen() -> Iterator[None]:
    yield
    clock.freeze(None)


def explain_everything(request: dict) -> dict:  # type: ignore[type-arg]
    """Claude's explanations: every wrong answer was a concept confusion."""
    count = request["messages"][0]["content"][0]["text"].count("Item ")
    items = [
        {
            "item": i,
            "why_wrong": "w",
            "correct_answer": "c",
            "reasoning": "r",
            "mistake": "Mixed up",
            "how_to_avoid": "h",
            "mistake_category": "concept_confusion",
        }
        for i in range(1, count + 1)
    ]
    return {"text": json.dumps({"items": items})}


async def test_practice_moves_to_the_weak_topic(db: AsyncSession, frozen: None) -> None:
    config = get_config()
    learner = random.Random(7)  # noqa: S311 - a simulation
    user = await make_user(db)
    module, topics, _ = await make_module(db, user, "MATH101", list(TRUE_SKILL))
    for topic in topics.values():
        await make_questions(db, user, module, topic, 15)
    title_of: dict[uuid.UUID | None, str] = {t.id: name for name, t in topics.items()}
    claude = ClaudeClient(FakeAnthropic(respond=explain_everything), config.ai)
    jobs = RecordingQueue()
    service = LearningService(db, user.id, ClientInfo(None, None), config=config, jobs=jobs)

    shares: list[Counter[str]] = []
    for day in range(DAYS):
        clock.freeze(START + timedelta(days=day))
        attempt, plan = await service.start_daily(minutes=15, rng=random.Random(day))  # noqa: S311
        assert plan.questions > 0
        answers = (
            await db.execute(
                select(QuestionAttempt, Question)
                .join(Question, Question.id == QuestionAttempt.question_id)
                .where(QuestionAttempt.quiz_attempt_id == attempt.id)
            )
        ).all()
        shares.append(Counter(title_of[q.topic_id] for _, q in answers))
        for answer, question in answers:
            right = learner.random() < TRUE_SKILL[title_of[question.topic_id]]
            answer.response = {"choice": 0 if right else 1}
            answer.time_ms = 60_000
        await db.commit()
        await submit_attempt(db, config, jobs, attempt)
        for name, args in jobs.jobs:
            if name == "mark_attempt":
                await mark_attempt(db, claude, config, uuid.UUID(args[0]))
        jobs.jobs.clear()
        status = await db.scalar(select(QuizAttempt.status).where(QuizAttempt.id == attempt.id))
        assert status == "marked"

    # Day one: nothing known, so the spread is even.
    first = shares[0]
    assert max(first.values()) - min(first.values()) <= 1, first

    # The last week: the weak topic gets the most practice, its share has
    # grown, and the strong topic gets less than an even share (it still comes
    # back now and then, when it becomes overdue).
    late = sum(shares[-7:], Counter())
    total = sum(late.values())
    assert late["Weak"] > late["Medium"] and late["Weak"] > late["Strong"], late
    assert late["Weak"] / total > first["Weak"] / sum(first.values())
    assert late["Strong"] / total < 1 / 3, late

    # The estimates recover the true order without being told it.
    mastery = {
        title_of[m.topic_id]: m
        for m in await db.scalars(select(TopicMastery).where(TopicMastery.user_id == user.id))
        if m.topic_id
    }
    strength = {name: m.strength for name, m in mastery.items()}
    assert strength["Strong"] > strength["Medium"] > strength["Weak"], strength
    # Elo ability is only meaningful against the same topic's question
    # ratings (both are fitted together), so compare predicted success: the
    # mean P(correct) over each topic's questions.
    ratings: dict[str, list[float]] = {}
    for question in await db.scalars(select(Question).where(Question.user_id == user.id)):
        ratings.setdefault(title_of[question.topic_id], []).append(question.rating)
    predicted = {
        name: sum(maths.expected_score(mastery[name].ability, b) for b in rs) / len(rs)
        for name, rs in ratings.items()
    }
    # The weak topic, practised most, is predicted lowest and close to the
    # truth; a strong topic, rarely practised, stays nearer the starting point.
    assert predicted["Weak"] < min(predicted["Medium"], predicted["Strong"]), predicted
    assert abs(predicted["Weak"] - TRUE_SKILL["Weak"]) < 0.15, predicted
    assert all(
        not m.weight < config.learning.mastery.low_data_weight_threshold for m in mastery.values()
    )
