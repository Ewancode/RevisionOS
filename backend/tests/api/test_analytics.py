"""Phase 9's acceptance test: every number on the dashboards traces to stored
data. A small, fully known history is seeded; each figure is checked against
a value worked out by hand from those rows, and every figure must say what
it was computed from."""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models import (
    Document,
    Exam,
    Flashcard,
    FlashcardReview,
    Material,
    Module,
    Question,
    QuestionAttempt,
    Quiz,
    QuizAttempt,
    QuizItem,
    StudySession,
    TopicMastery,
    User,
)
from tests.learning_support import make_module, make_questions
from tests.support import make_user, signed_in

pytestmark = pytest.mark.db

NOW = datetime(2026, 10, 5, 9, tzinfo=UTC)  # Monday 10:00 in London
TODAY = date(2026, 10, 5)


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


async def _get(client: httpx.AsyncClient, path: str) -> Any:
    response = await client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


async def answer(
    db: AsyncSession,
    user: User,
    question: Question,
    score: float,
    at: datetime,
    *,
    time_ms: int | None = 60_000,
    mistake: str | None = None,
) -> None:
    """A marked answer in its own practice quiz."""
    quiz = Quiz(
        id=uuid.uuid4(), user_id=user.id, module_id=question.module_id, kind="practice", title="Q"
    )
    db.add(quiz)
    await db.flush()
    attempt = QuizAttempt(
        id=uuid.uuid4(),
        user_id=user.id,
        quiz_id=quiz.id,
        mode="normal",
        status="marked",
        submitted_at=at,
        marked_at=at,
        score=score,
    )
    db.add_all(
        [QuizItem(quiz_id=quiz.id, position=0, user_id=user.id, question_id=question.id), attempt]
    )
    await db.flush()
    db.add(
        QuestionAttempt(
            id=uuid.uuid4(),
            user_id=user.id,
            quiz_attempt_id=attempt.id,
            question_id=question.id,
            score=score,
            marked_at=at,
            marked_by="rule",
            time_ms=time_ms,
            mistake_category=mistake,
        )
    )
    await db.flush()


def metrics(node: Any, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    """Every {value, basis} figure in a response."""
    if isinstance(node, dict):
        if set(node) == {"value", "basis"}:
            yield path, node
            return
        for key, child in node.items():
            yield from metrics(child, f"{path}.{key}")
    elif isinstance(node, list):
        for i, child in enumerate(node):
            yield from metrics(child, f"{path}[{i}]")


def assert_traceable(response: Any) -> None:
    found = list(metrics(response))
    assert found
    for path, metric in found:
        assert len(metric["basis"]) > 10, (path, metric)


@pytest.fixture
async def history(owner: User, db: AsyncSession) -> dict[str, Any]:
    """MATH101 (Limits, Series) with an exam in 10 days; STAT101 untouched."""
    module, topics, year = await make_module(db, owner, "MATH101", ["Limits", "Series"])
    stat, _, _ = await make_module(db, owner, "STAT101", ["Probability"], year)
    series_q = await make_questions(db, owner, module, topics["Series"], 4)
    [limits_q] = await make_questions(db, owner, module, topics["Limits"], 1)
    # This week: four answers on Series (two right, a half mark, a zero), one
    # minute each; two were sign errors.
    for q, score, mistake in zip(
        series_q, (1.0, 1.0, 0.5, 0.0), (None, None, "sign_error", "sign_error"), strict=True
    ):
        await answer(db, owner, q, score, NOW - timedelta(hours=1), mistake=mistake)
    # Twenty days ago: one answer on Limits.
    await answer(db, owner, limits_q, 0.0, NOW - timedelta(days=20))
    card = Flashcard(
        id=uuid.uuid4(),
        user_id=owner.id,
        module_id=module.id,
        front_md="f",
        back_md="b",
        origin="user",
        due=NOW + timedelta(days=3),
    )
    db.add(card)
    await db.flush()
    for at, ms in (
        (NOW - timedelta(minutes=5), 20_000),
        (NOW - timedelta(days=1), 30_000),
        (NOW - timedelta(days=1), None),
    ):
        db.add(
            FlashcardReview(
                user_id=owner.id,
                flashcard_id=card.id,
                rating=3,
                reviewed_at=at,
                state_before=2,
                scheduled_days=3.0,
                duration_ms=ms,
            )
        )
    db.add_all(
        [
            TopicMastery(
                user_id=owner.id,
                module_id=module.id,
                topic_id=topics["Series"].id,
                strength=0.75,
                accuracy=0.7,
                weight=6.0,
                attempts=4,
                ability=1500,
                last_practised_at=NOW - timedelta(days=1),
                computed_at=NOW,
            ),
            TopicMastery(
                user_id=owner.id,
                module_id=module.id,
                topic_id=topics["Limits"].id,
                strength=0.4,
                accuracy=0.4,
                weight=2.0,
                attempts=1,
                ability=1500,
                last_practised_at=NOW - timedelta(days=10),
                computed_at=NOW,
            ),
            Exam(
                id=uuid.uuid4(),
                user_id=owner.id,
                module_id=module.id,
                title="MATH101 final",
                starts_at=NOW + timedelta(days=10),
                duration_minutes=120,
            ),
            StudySession(
                id=uuid.uuid4(),
                user_id=owner.id,
                module_id=module.id,
                topic_id=topics["Series"].id,
                kind="topic",
                day=TODAY,
                minutes=45,
                status="done",
                reason="r",
            ),
            StudySession(
                id=uuid.uuid4(),
                user_id=owner.id,
                module_id=module.id,
                topic_id=topics["Limits"].id,
                kind="topic",
                day=TODAY,
                minutes=45,
                status="planned",
                reason="r",
            ),
            StudySession(
                id=uuid.uuid4(),
                user_id=owner.id,
                module_id=module.id,
                topic_id=topics["Limits"].id,
                kind="topic",
                day=TODAY - timedelta(days=1),
                minutes=45,
                status="done",
                reason="r",
            ),
            StudySession(
                id=uuid.uuid4(),
                user_id=owner.id,
                module_id=module.id,
                topic_id=topics["Limits"].id,
                kind="topic",
                day=TODAY - timedelta(days=3),
                minutes=45,
                status="missed",
                reason="r",
            ),
        ]
    )
    mock = Quiz(id=uuid.uuid4(), user_id=owner.id, module_id=module.id, kind="mock", title="Mock")
    db.add(mock)
    await db.flush()
    db.add(
        QuizAttempt(
            id=uuid.uuid4(),
            user_id=owner.id,
            quiz_id=mock.id,
            mode="exam",
            status="marked",
            submitted_at=NOW - timedelta(days=2),
            marked_at=NOW - timedelta(days=2),
            score=0.6,
        )
    )
    db.add(
        Material(
            id=uuid.uuid4(),
            user_id=owner.id,
            module_id=module.id,
            title="Series summary",
            kind="summary",
            origin="claude",
        )
    )
    await db.commit()
    return {"module": module, "stat": stat, "topics": topics}


async def test_every_dashboard_number_traces_to_stored_data(
    client: httpx.AsyncClient, history: dict[str, Any]
) -> None:
    o = await _get(client, "/api/v1/analytics/overview")
    assert_traceable(o)

    # Today: 45 of 90 planned minutes done, plus today's quiz (15% of the
    # weekday's 120 minutes = 18) not done: 45 / 108.
    assert o["today"]["planned_minutes"] == 108 and o["today"]["done_minutes"] == 45
    assert o["today"]["progress"]["value"] == pytest.approx(45 / 108)
    assert o["today"]["progress"]["basis"] == (
        "Today: 1 of 2 planned sessions done (45 of 90 min); daily quiz not done (18 min)"
    )
    # Active today and yesterday; 20 days ago is a separate run.
    assert o["streak"]["current"]["value"] == 2
    assert o["streak"]["longest"]["value"] == 2

    r = o["recent"]
    assert (r["answered"]["value"], r["correct"]["value"], r["reviews"]["value"]) == (4, 2, 3)
    assert r["accuracy"]["value"] == pytest.approx(0.625)
    # 4 × 60 s of answers + 20 s + 30 s of reviews = 290 s; the untimed review adds nothing.
    assert r["study_minutes"]["value"] == 5
    assert "1 without a recorded time not counted" in r["study_minutes"]["basis"]
    assert r["mistakes"]["value"] == 2 and r["mistakes"]["basis"].endswith("sign error 2")

    math, stat = o["modules"]
    assert math["code"] == "MATH101"
    assert math["progress"]["value"] == pytest.approx((6 * 0.75 + 2 * 0.4) / 8)
    assert math["coverage"]["value"] == 0.5
    assert math["coverage"]["basis"] == "1 of 2 topics with at least 3 marked answers"
    assert math["mastered"]["value"] == 0
    assert stat["progress"] == {
        "value": None,
        "basis": "No marked answers or flashcard reviews in this module yet",
    }
    assert [t["title"] for t in o["strong"]] == ["Series"]
    assert o["mistake_groups"]["value"] == 1
    assert [m["title"] for m in o["materials"]] == ["Series summary"]

    # Exam readiness: coverage 1/2, strength (0.4 + 0.75) / 2, recent mark
    # 0.625 (the answer 20 days ago is outside 14), mock 0.6, recency 1/2.
    [ready] = await _get(client, "/api/v1/analytics/readiness")
    assert_traceable(ready)
    c = {k: v["value"] for k, v in ready["components"].items()}
    assert c == pytest.approx(
        {"coverage": 0.5, "strength": 0.575, "recent": 0.625, "mock": 0.6, "recency": 0.5}
    )
    expected = 0.25 * 0.5 + 0.3 * 0.575 + 0.2 * 0.625 + 0.15 * 0.6 + 0.1 * 0.5
    assert ready["index"] == pytest.approx(expected)
    assert ready["band"] == "Building" and ready["days_until"] == 10
    assert [t["title"] for t in ready["weak_topics"]] == ["Limits"]
    assert "not a prediction" in ready["note"]


async def test_trends_add_up_to_the_stored_events(
    client: httpx.AsyncClient, history: dict[str, Any]
) -> None:
    t = await _get(client, "/api/v1/analytics/trends")
    weeks = {w["start"]: w for w in t["weeks"]}
    this, last = weeks["2026-10-05"], weeks["2026-09-28"]
    assert (this["answered"], this["reviews"], this["sessions_done"]) == (4, 1, 1)
    assert this["accuracy"] == pytest.approx(0.625) and this["mistakes"] == {"sign_error": 2}
    assert this["study_minutes"] == round((4 * 60 + 20) / 60)
    # Last week: two reviews and a done session on Sunday, a missed one on Friday.
    assert (last["answered"], last["reviews"]) == (0, 2)
    assert (last["sessions_done"], last["sessions_planned"]) == (1, 2)
    assert sum(w["answered"] for w in t["weeks"]) == 5
    days = {d["day"]: d["events"] for d in t["days"]}
    # Today: 4 answers + 1 review + 1 done session.
    assert days["2026-10-05"] == 6 and days["2026-10-04"] == 3
    assert t["mistake_labels"]["sign_error"] == "Sign error"
    assert set(t["basis"]) == {"accuracy", "study_time", "mistakes", "consistency"}

    only_stat = await _get(client, f"/api/v1/analytics/trends?module_id={history['stat'].id}")
    assert sum(w["answered"] + w["reviews"] for w in only_stat["weeks"]) == 0


async def test_the_module_dashboard(client: httpx.AsyncClient, history: dict[str, Any]) -> None:
    m = await _get(client, f"/api/v1/analytics/modules/{history['module'].id}")
    assert_traceable(m)
    assert m["progress"]["value"] == pytest.approx(0.6625)
    assert m["recent"]["answered"]["value"] == 4
    assert m["readiness"]["title"] == "MATH101 final"
    # Limits: weakest, on the exam; the recommendation names its evidence.
    rec = m["recommendation"]
    assert rec["title"] == "Limits" and rec["reason"].startswith("est. 40%")
    assert "exam in 10 days" in rec["reason"]

    stat = await _get(client, f"/api/v1/analytics/modules/{history['stat'].id}")
    assert stat["readiness"] is None
    assert stat["recent"]["accuracy"] == {
        "value": None,
        "basis": "No answers marked in the last 7 days",
    }


async def test_an_empty_account_shows_no_invented_numbers(
    client: httpx.AsyncClient, owner: User, db: AsyncSession
) -> None:
    await make_module(db, owner, "MATH101", ["Limits"])
    o = await _get(client, "/api/v1/analytics/overview")
    assert_traceable(o)
    assert o["streak"]["current"]["value"] == 0
    assert o["recent"]["accuracy"]["value"] is None
    assert o["modules"][0]["progress"]["value"] is None
    assert o["today"]["progress"] == {"value": None, "basis": "Nothing planned today"}
    assert not o["strong"] and not o["weak"] and not o["uploads"]
    assert await _get(client, "/api/v1/analytics/readiness") == []


async def test_documents_appear_as_recent_uploads(
    client: httpx.AsyncClient, history: dict[str, Any], db: AsyncSession, owner: User
) -> None:
    module: Module = history["module"]
    db.add(
        Document(
            id=uuid.uuid4(),
            user_id=owner.id,
            module_id=module.id,
            original_filename="Week 3.pdf",
            storage_key=f"u/{uuid.uuid4()}",
            mime="application/pdf",
            size_bytes=10,
            sha256=b"\0" * 32,
            source_tier="university",
            material_kind="lecture",
        )
    )
    await db.commit()
    o = await _get(client, "/api/v1/analytics/overview")
    assert [(u["filename"], u["module_code"]) for u in o["uploads"]] == [("Week 3.pdf", "MATH101")]


async def test_todays_panels_put_the_pressing_first(
    client: httpx.AsyncClient, history: dict[str, Any]
) -> None:
    """MATH101's exam is in 10 days (not yet "soon"); 3 reviews but under 10
    cards due; questions exist and today's quiz is not done."""
    panels = (await _get(client, "/api/v1/analytics/dashboard"))["panels"]
    keys = [p["key"] for p in panels]
    assert keys[0] == "daily_quiz"
    assert panels[0]["reason"] == "Today's quiz is not done yet"
    assert sorted(keys) == sorted(
        ["glance", "recommended", "todays_revision", "daily_quiz", "flashcards", "builder",
         "exams", "weak_topics", "mistakes", "recent"]
    )  # fmt: skip
