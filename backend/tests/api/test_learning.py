"""Adaptive learning through the API: flashcard reviews, progress, the daily
quiz (with its top-up), the mistake bank, the profile and the assistant's
progress tool."""

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import get_config
from app.ingestion.pipeline import Deps
from app.learning.summary import summarise
from app.models import (
    Draft,
    Flashcard,
    LearningProfileSnapshot,
    Module,
    Question,
    QuestionAttempt,
    User,
)
from app.practice.generation import run_draft
from app.practice.marking import mark_attempt
from tests import factories
from tests.fakes import FakeAnthropic, RecordingQueue, reply, text, tool_use
from tests.learning_support import make_module, make_questions
from tests.support import create_module, ingest, make_user, signed_in

pytestmark = pytest.mark.db

LEARNING = get_config().learning
NOW = datetime(2026, 10, 5, 9, tzinfo=UTC)


@pytest.fixture(autouse=True)
def frozen() -> Iterator[None]:
    clock.freeze(NOW)
    yield
    clock.freeze(None)


@pytest.fixture
async def owner(db: AsyncSession) -> User:
    return await make_user(db)


@pytest.fixture
async def client(db_app: FastAPI, owner: User) -> AsyncIterator[httpx.AsyncClient]:
    async with signed_in(db_app, owner) as c:
        yield c


async def _json(client: httpx.AsyncClient, method: str, path: str, **kw: Any) -> Any:
    response = await client.request(method, path, **kw)
    assert response.status_code < 300, response.text
    return response.json() if response.content else None


async def _answer(
    client: httpx.AsyncClient, attempt_id: str, right: Any = lambda item: True
) -> dict[str, Any]:
    """Answer every (multiple-choice) item, right or wrong, and submit."""
    attempt = await _json(client, "GET", f"/api/v1/attempts/{attempt_id}")
    for item in attempt["items"]:
        choice = 0 if right(item) else 1
        await _json(
            client,
            "PUT",
            f"/api/v1/attempts/{attempt_id}/responses/{item['question_id']}",
            json={"response": {"choice": choice}, "time_ms": 45_000},
        )
    return dict(await _json(client, "POST", f"/api/v1/attempts/{attempt_id}/submit"))


# --- flashcards ------------------------------------------------------------------------------


async def test_reviewing_flashcards_schedules_them(
    client: httpx.AsyncClient, owner: User, db: AsyncSession
) -> None:
    module, topics, _ = await make_module(db, owner, "MATH101", ["Series"])
    for n in range(3):
        db.add(
            Flashcard(
                id=uuid.uuid4(),
                user_id=owner.id,
                module_id=module.id,
                topic_id=topics["Series"].id,
                front_md=f"Card {n}",
                back_md="b",
                origin="user",
                due=NOW - timedelta(minutes=n),
            )
        )
    await db.commit()

    due = await _json(client, "GET", f"/api/v1/flashcards/due?module_id={module.id}")
    assert due["counts"] == {"due": 3, "review": 0, "learning": 0, "new": 3}
    card = due["cards"][0]
    assert card["fsrs_state"] == 1
    assert card["intervals"]["1"] < card["intervals"]["3"] < card["intervals"]["4"]

    reviewed = await _json(
        client, "POST", f"/api/v1/flashcards/{card['id']}/review", json={"rating": 4}
    )
    assert reviewed["reps"] == 1 and reviewed["fsrs_state"] == 2
    assert datetime.fromisoformat(reviewed["due"]) > NOW + timedelta(days=1)
    due = await _json(client, "GET", "/api/v1/flashcards/due")
    assert due["counts"]["due"] == 2
    bad = await client.post(f"/api/v1/flashcards/{card['id']}/review", json={"rating": 5})
    assert bad.status_code == 422

    # Recall now counts towards the topic's strength.
    progress = await _json(client, "GET", f"/api/v1/progress?module_id={module.id}")
    series = next(p for p in progress if p["title"] == "Series")
    assert series["retrievability"] is not None and series["attempts"] == 0


async def test_new_cards_are_limited_per_day(
    client: httpx.AsyncClient, owner: User, db: AsyncSession
) -> None:
    module, _, _ = await make_module(db, owner, "MATH101", [])
    limit = LEARNING.spaced_repetition.new_cards_per_day
    for n in range(limit + 5):
        db.add(
            Flashcard(
                id=uuid.uuid4(),
                user_id=owner.id,
                module_id=module.id,
                front_md=f"{n}",
                back_md="b",
                origin="user",
                due=NOW - timedelta(hours=1),
            )
        )
    await db.commit()
    due = await _json(client, "GET", "/api/v1/flashcards/due")
    assert due["counts"]["new"] == limit


# --- progress and the daily quiz ------------------------------------------------------------


async def test_the_daily_quiz_spreads_evenly_then_follows_results(
    client: httpx.AsyncClient, owner: User, db: AsyncSession, queue: RecordingQueue, deps: Deps
) -> None:
    calculus, c_topics, year = await make_module(db, owner, "MATH101", ["Limits", "Series"])
    stats, s_topics, _ = await make_module(db, owner, "STAT101", ["Probability"], year)
    for module, topics in ((calculus, c_topics), (stats, s_topics)):
        for topic in topics.values():
            await make_questions(db, owner, module, topic, 6)

    plan = await _json(client, "GET", "/api/v1/daily-quiz/plan?minutes=12")
    assert plan["questions"] == 8  # 12 minutes at the default 90 s per question
    allocated = {b["title"]: b["allocated"] for b in plan["buckets"]}
    assert max(allocated.values()) - min(allocated.values()) <= 1
    assert all("not practised yet" in b["reasons"] for b in plan["buckets"])

    started = await _json(client, "POST", "/api/v1/daily-quiz", json={"minutes": 12})
    again = await _json(client, "POST", "/api/v1/daily-quiz", json={})
    assert again["attempt_id"] == started["attempt_id"]  # one daily quiz a day
    attempt = await _json(client, "GET", f"/api/v1/attempts/{started['attempt_id']}")
    assert attempt["quiz"]["kind"] == "daily" and attempt["quiz"]["module_id"] is None
    modules = {item["topic_id"] for item in attempt["items"]}
    assert len(modules) == 3

    # Everything in Limits wrong, everything else right.
    limits = str(c_topics["Limits"].id)
    await _answer(client, started["attempt_id"], right=lambda item: item["topic_id"] != limits)
    [(_, args)] = queue.jobs  # the wrong answers are explained, then strength recomputed
    async with deps.sessions() as session:
        await mark_attempt(session, deps.claude, deps.config, uuid.UUID(args[0]))

    progress = await _json(client, "GET", f"/api/v1/progress?module_id={calculus.id}")
    by_title = {p["title"]: p for p in progress}
    assert by_title["Limits"]["strength"] < by_title["Series"]["strength"]
    assert by_title["Limits"]["attempts"] > 0 and by_title["Limits"]["low_data"]
    weakest = await _json(client, "GET", "/api/v1/progress/weakest")
    assert weakest[0]["title"] == "Limits"

    clock.freeze(NOW + timedelta(days=1))
    plan = await _json(client, "GET", "/api/v1/daily-quiz/plan?minutes=12")
    allocated = {b["title"]: b["allocated"] for b in plan["buckets"]}
    assert allocated["Limits"] == max(allocated.values())
    history = await _json(client, "GET", "/api/v1/attempts")
    assert history[0]["kind"] == "daily"


async def test_a_parent_topic_includes_its_subtopics(
    client: httpx.AsyncClient, deps: Deps, queue: RecordingQueue, tmp_path: Any
) -> None:
    module = await create_module(client, "MATH101")
    parent = await _json(
        client, "POST", f"/api/v1/modules/{module['id']}/topics", json={"title": "Calculus"}
    )
    await _json(
        client,
        "POST",
        f"/api/v1/modules/{module['id']}/topics",
        json={"title": "Series", "parent_id": parent["id"]},
    )
    progress = await _json(client, "GET", f"/api/v1/progress?module_id={module['id']}")
    assert {p["title"]: p["parent_id"] for p in progress}["Series"] == parent["id"]
    assert all(p["low_data"] for p in progress)


async def test_mistakes_group_into_recurring_patterns(
    client: httpx.AsyncClient, owner: User, db: AsyncSession
) -> None:
    module, topics, _ = await make_module(db, owner, "MATH101", ["Integration"])
    questions = await make_questions(db, owner, module, topics["Integration"], 4)
    started = await _json(
        client,
        "POST",
        "/api/v1/quizzes",
        json={"module_id": str(module.id), "question_ids": [str(q.id) for q in questions]},
    )
    await _answer(client, started["attempt_id"], right=lambda item: False)
    answers = (
        await db.scalars(
            select(QuestionAttempt).where(
                QuestionAttempt.quiz_attempt_id == uuid.UUID(started["attempt_id"])
            )
        )
    ).all()
    for n, answer in enumerate(answers):
        await db.refresh(answer)
        answer.mistake_category = "sign_error" if n < 3 else "notation"
        answer.feedback = {"explanation": {"mistake": "Dropped the minus sign" if n < 3 else "x"}}
        answer.marked_at = NOW
    await db.commit()

    groups = await _json(client, "GET", f"/api/v1/mistakes?module_id={module.id}")
    first = groups[0]
    assert (first["category"], first["count"], first["recurring"]) == ("sign_error", 3, True)
    assert first["label"] == "Sign error"
    assert first["patterns"] == [{"description": "Dropped the minus sign", "count": 3}]
    assert groups[1]["recurring"] is False

    # The daily quiz names it and aims questions at it.
    plan = await _json(client, "GET", "/api/v1/daily-quiz/plan")
    integration = next(b for b in plan["buckets"] if b["title"] == "Integration")
    assert "recurring sign error" in integration["reasons"]
    assert integration["terms"]["recurring"] == 1.0


async def test_thin_topics_are_topped_up_with_checked_questions(
    client: httpx.AsyncClient,
    course_owner: tuple[User, str],
    fake_claude: FakeAnthropic,
    queue: RecordingQueue,
    deps: Deps,
    db: AsyncSession,
) -> None:
    owner, module_id = course_owner
    topic = await _json(
        client, "POST", f"/api/v1/modules/{module_id}/topics", json={"title": "Options"}
    )
    module = await db.get(Module, uuid.UUID(module_id))
    assert module is not None
    await make_questions(db, owner, module, None, 3)  # something to practise today
    item = {
        "type": "true_false",
        "difficulty": "easy",
        "stem_md": "Volatility is constant in Black-Scholes.",
        "solution_md": "It is assumed.",
        "sources": [1],
        "true_or_false": True,
        **dict.fromkeys(
            [
                "options",
                "correct_option",
                "value",
                "tolerance",
                "relative_tolerance",
                "unit",
                "check",
                "expression",
                "variables",
                "accepted_answers",
                "rubric",
                "model_answer",
            ]
        ),
    }
    fake_claude.respond = lambda _: {"text": json.dumps({"items": [item]})}

    await _json(client, "POST", "/api/v1/daily-quiz", json={})
    [(_, args)] = [job for job in queue.jobs if job[0] == "generate_draft"]
    draft = await db.get(Draft, uuid.UUID(args[0]))
    assert draft is not None and draft.request["auto"] is True
    assert str(draft.topic_id) == topic["id"]
    queue.jobs.clear()
    async with deps.sessions() as session:
        await run_draft(session, deps.claude, deps.embedder, deps.config, draft.id)
    await db.refresh(draft)
    assert draft.status == "saved"  # no preview needed for quiz questions
    saved = (
        await db.scalars(select(Question).where(Question.topic_id == uuid.UUID(topic["id"])))
    ).all()
    assert len(saved) == 1

    # Only so many topics a day.
    await _json(client, "POST", "/api/v1/daily-quiz", json={})
    assert not [job for job in queue.jobs if job[0] == "generate_draft"]


@pytest.fixture
async def course_owner(
    client: httpx.AsyncClient, owner: User, deps: Deps, queue: RecordingQueue, tmp_path: Any
) -> tuple[User, str]:
    module = await create_module(client, "MATH260")
    await ingest(
        client,
        deps,
        queue,
        module["id"],
        factories.pdf(tmp_path / "l.pdf", ["Black-Scholes assumes constant volatility."]),
        "W1.pdf",
    )
    return owner, str(module["id"])


async def test_no_daily_quiz_without_questions(
    client: httpx.AsyncClient, owner: User, db: AsyncSession
) -> None:
    await make_module(db, owner, "MATH101", ["Empty"])
    response = await client.post("/api/v1/daily-quiz", json={})
    assert response.status_code == 422 and response.json()["error"]["code"] == "no_questions"


async def test_overriding_a_mark_updates_strength(
    client: httpx.AsyncClient, owner: User, db: AsyncSession, queue: RecordingQueue, deps: Deps
) -> None:
    module, topics, _ = await make_module(db, owner, "MATH101", ["Series"])
    questions = await make_questions(db, owner, module, topics["Series"], 2)
    started = await _json(
        client,
        "POST",
        "/api/v1/quizzes",
        json={"module_id": str(module.id), "question_ids": [str(q.id) for q in questions]},
    )
    marked = await _answer(client, started["attempt_id"], right=lambda item: False)
    # Wrong answers go to the worker to be explained; marking then recomputes.
    [(_, args)] = queue.jobs
    async with deps.sessions() as session:
        await mark_attempt(session, deps.claude, deps.config, uuid.UUID(args[0]))
    before = (await _json(client, "GET", f"/api/v1/progress?module_id={module.id}"))[0]
    assert before["attempts"] == 2
    answer = marked["items"][0]["question_attempt_id"]
    await _json(client, "POST", f"/api/v1/answers/{answer}/override", json={"score": 1})
    after = (await _json(client, "GET", f"/api/v1/progress?module_id={module.id}"))[0]
    assert after["strength"] > before["strength"]


# --- profile ------------------------------------------------------------------------------------


async def test_the_profile_reports_measurements_and_a_weekly_summary(
    client: httpx.AsyncClient,
    owner: User,
    db: AsyncSession,
    queue: RecordingQueue,
    deps: Deps,
    fake_claude: FakeAnthropic,
) -> None:
    module, topics, _ = await make_module(db, owner, "MATH101", ["Series"])
    questions = await make_questions(db, owner, module, topics["Series"], 12)
    started = await _json(
        client,
        "POST",
        "/api/v1/quizzes",
        json={"module_id": str(module.id), "question_ids": [str(q.id) for q in questions]},
    )
    await _answer(client, started["attempt_id"], right=lambda item: item["position"] % 3 != 0)
    queue.jobs.clear()

    profile = await _json(client, "GET", "/api/v1/profile")
    current = profile["current"]
    assert current["answered"] == 12
    assert current["by_type"]["multiple_choice"] == {
        "answered": 12,
        "accuracy": pytest.approx(8 / 12, abs=1e-3),
    }
    assert current["untimed"]["answered"] == 12 and current["exam_conditions"] is None
    snapshot = profile["snapshot"]
    assert snapshot is not None and snapshot["summary_md"] is None
    [(name, args)] = queue.jobs
    assert name == "summarise_profile"

    fake_claude.respond = lambda _: {"text": "- You answered 12 questions; 67% were right."}
    async with deps.sessions() as session:
        await summarise(session, deps.claude, deps.config, args[0])
    profile = await _json(client, "GET", "/api/v1/profile")
    assert profile["snapshot"]["summary_md"].startswith("- You answered 12")
    request = fake_claude.requests[-1]
    assert '"answered": 12' in request["messages"][0]["content"][0]["text"]
    assert (await db.scalars(select(LearningProfileSnapshot))).one().ai_interaction_id is not None


# --- the assistant ------------------------------------------------------------------------


async def test_the_assistant_reads_your_progress(
    client: httpx.AsyncClient, owner: User, db: AsyncSession, fake_claude: FakeAnthropic
) -> None:
    module, topics, _ = await make_module(db, owner, "MATH101", ["Series"])
    await make_questions(db, owner, module, topics["Series"], 3)
    fake_claude.stream_script = [
        reply(tool_use("get_progress", {})),
        reply(text("You have no marked answers yet.")),
    ]
    conversation = (await client.post("/api/v1/conversations", json={})).json()["id"]
    await client.post(
        f"/api/v1/conversations/{conversation}/messages", json={"content": "How am I doing?"}
    )
    [result] = fake_claude.requests[1]["messages"][-1]["content"]
    assert "No marked answers yet" in result["content"]
    assert "Flashcards due now: 0" in result["content"]
    assert "Today's daily quiz would have" in result["content"]
