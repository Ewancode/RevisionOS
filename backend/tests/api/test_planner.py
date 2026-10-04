"""The revision planner end to end: exams, availability (including Claude's
reading of plain English), the plan and rebalancing, the calendar, "I have
45 minutes", notifications, and how exams feed the daily quiz and flashcards."""

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import get_config
from app.models import Flashcard, QuestionAttempt, StudySession, Topic, TopicMastery, User
from tests.fakes import FakeAnthropic, reply, text, tool_use
from tests.learning_support import make_module, make_questions
from tests.support import make_user, signed_in

pytestmark = pytest.mark.db

PLANNER = get_config().planner
NOW = datetime(2026, 10, 5, 9, tzinfo=UTC)  # a Monday, 10:00 in London
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


async def _json(client: httpx.AsyncClient, method: str, path: str, **kw: Any) -> Any:
    response = await client.request(method, path, **kw)
    assert response.status_code < 300, response.text
    return response.json() if response.content else None


@pytest.fixture
async def course(owner: User, db: AsyncSession) -> dict[str, Any]:
    """MATH101 with three topics of different strengths."""
    module, topics, year = await make_module(
        db, owner, "MATH101", ["Limits", "Series", "Integration"]
    )
    strengths = {"Limits": 0.85, "Series": 0.55, "Integration": 0.3}
    for title, topic in topics.items():
        await make_questions(db, owner, module, topic, 3)
        db.add(
            TopicMastery(
                user_id=owner.id,
                module_id=module.id,
                topic_id=topic.id,
                strength=strengths[title],
                accuracy=strengths[title],
                weight=8.0,
                attempts=10,
                ability=1500,
                last_practised_at=NOW - timedelta(days=6),
                computed_at=NOW - timedelta(hours=1),
            )
        )
    await db.commit()
    return {"module": module, "topics": topics, "year": year}


async def _exam(
    client: httpx.AsyncClient, module_id: Any, days: int, **extra: Any
) -> dict[str, Any]:
    starts = (NOW + timedelta(days=days)).replace(hour=9)
    return dict(
        await _json(
            client,
            "POST",
            "/api/v1/exams",
            json={
                "module_id": str(module_id),
                "title": "MATH101 final",
                "starts_at": starts.isoformat(),
                "duration_minutes": 120,
                **extra,
            },
        )
    )


# --- exams and the plan ----------------------------------------------------------------------


async def test_an_exam_produces_a_plan_that_favours_weak_topics(
    client: httpx.AsyncClient, course: dict[str, Any]
) -> None:
    exam = await _exam(client, course["module"].id, 20, weighting=60, confidence=2)
    assert exam["days_until"] == 20 and exam["topic_ids"] == []

    plan = await _json(client, "GET", "/api/v1/plan")
    sessions = plan["today"] + plan["upcoming"]
    assert sessions and not plan["shortfalls"]
    minutes: dict[str, int] = {}
    for s in sessions:
        if s["kind"] == "topic":
            minutes[s["title"]] = minutes.get(s["title"], 0) + s["minutes"]
    assert minutes["Integration"] > minutes["Series"] > minutes["Limits"] > 0
    integration = next(s for s in sessions if s["title"] == "Integration")
    assert (
        "est. 30%" in integration["reason"] and "MATH101 exam in 20 days" in integration["reason"]
    )
    # Daily capacity: weekdays 120 minutes by default, less the quiz and card reserves.
    by_day: dict[str, int] = {}
    for s in sessions:
        by_day[s["day"]] = by_day.get(s["day"], 0) + s["minutes"]
    assert max(by_day.values()) <= PLANNER.availability.default_weekday_minutes
    assert plan["exams"][0]["title"] == "MATH101 final"


async def test_a_mock_exam_is_planned_in_the_final_week(
    client: httpx.AsyncClient, course: dict[str, Any]
) -> None:
    await _exam(client, course["module"].id, 12)
    calendar = await _json(
        client, "GET", f"/api/v1/calendar?start={TODAY}&end={TODAY + timedelta(days=13)}"
    )
    mocks = [s for d in calendar["days"] for s in d["sessions"] if s["kind"] == "mock_exam"]
    assert len(mocks) == 1
    assert date.fromisoformat(mocks[0]["day"]) == TODAY + timedelta(
        days=12 - PLANNER.allocation.mock_exam_days_before
    )
    exam_day = next(d for d in calendar["days"] if d["exams"])
    assert exam_day["day"] == (TODAY + timedelta(days=12)).isoformat()
    bad = await client.get(f"/api/v1/calendar?start={TODAY}&end={TODAY + timedelta(days=90)}")
    assert bad.status_code == 422


async def test_an_exam_on_chosen_topics_only_plans_those(
    client: httpx.AsyncClient, course: dict[str, Any]
) -> None:
    series = course["topics"]["Series"]
    await _exam(client, course["module"].id, 10, topic_ids=[str(series.id)])
    plan = await _json(client, "GET", "/api/v1/plan")
    exam_sessions = [
        s for s in plan["today"] + plan["upcoming"] if s["exam_id"] and s["kind"] == "topic"
    ]
    assert {s["title"] for s in exam_sessions} == {"Series"}


async def test_moving_a_session_locks_it_and_rebalances_the_rest(
    client: httpx.AsyncClient, course: dict[str, Any]
) -> None:
    await _exam(client, course["module"].id, 14)
    plan = await _json(client, "GET", "/api/v1/plan")
    first = (plan["today"] + plan["upcoming"])[0]
    target = (TODAY + timedelta(days=5)).isoformat()
    moved = await _json(
        client, "PATCH", f"/api/v1/sessions/{first['id']}", json={"day": target, "minutes": 30}
    )
    assert moved["locked"] and moved["day"] == target and moved["minutes"] == 30

    # Anything that replans leaves it where you put it.
    await _json(client, "PUT", "/api/v1/availability", json={"weekdays": [90] * 7, "overrides": []})
    plan = await _json(client, "GET", "/api/v1/plan")
    kept = next(s for s in plan["upcoming"] if s["id"] == first["id"])
    assert kept["day"] == target and kept["locked"]
    past = await client.patch(f"/api/v1/sessions/{first['id']}", json={"day": "2026-01-01"})
    assert past.status_code == 422


async def test_done_and_missed_sessions(
    client: httpx.AsyncClient, course: dict[str, Any], db: AsyncSession
) -> None:
    await _exam(client, course["module"].id, 14)
    plan = await _json(client, "GET", "/api/v1/plan")
    today = plan["today"]
    assert today
    done = await _json(
        client,
        "POST",
        f"/api/v1/sessions/{today[0]['id']}/status",
        json={"status": "done", "actual_minutes": 50},
    )
    assert done["status"] == "done" and done["actual_minutes"] == 50

    # The next day, today's other sessions were missed; done stays done.
    clock.freeze(NOW + timedelta(days=1))
    await _json(client, "GET", "/api/v1/plan")
    statuses = {
        s.id: s.status
        for s in await db.scalars(select(StudySession).where(StudySession.day == TODAY))
    }
    assert statuses[uuid.UUID(today[0]["id"])] == "done"
    assert all(v in ("done", "missed") for v in statuses.values())


async def test_too_little_time_is_reported_not_crammed(
    client: httpx.AsyncClient, course: dict[str, Any]
) -> None:
    await _json(client, "PUT", "/api/v1/availability", json={"weekdays": [30] * 7, "overrides": []})
    await _exam(client, course["module"].id, 3, weighting=100, confidence=1)
    plan = await _json(client, "GET", "/api/v1/plan")
    [shortfall] = plan["shortfalls"]
    assert shortfall["reason"] == "time"
    assert shortfall["needed_minutes"] > shortfall["available_minutes"]
    assert shortfall["planned_minutes"] < shortfall["needed_minutes"]


async def test_rest_days_and_overrides_shape_the_plan(
    client: httpx.AsyncClient, course: dict[str, Any]
) -> None:
    await _json(client, "PATCH", "/api/v1/planner/preferences", json={"rest_weekdays": [2]})
    tomorrow = TODAY + timedelta(days=1)
    await _json(
        client,
        "PUT",
        "/api/v1/availability",
        json={"weekdays": [None] * 7, "overrides": [{"day": tomorrow.isoformat(), "minutes": 0}]},
    )
    await _exam(client, course["module"].id, 14)
    calendar = await _json(
        client, "GET", f"/api/v1/calendar?start={TODAY}&end={TODAY + timedelta(days=13)}"
    )
    for day in calendar["days"]:
        d = date.fromisoformat(day["day"])
        if d.weekday() == 2 or d == tomorrow:
            assert day["available_minutes"] == 0 and not day["sessions"], day
    availability = await _json(client, "GET", "/api/v1/availability")
    assert availability["overrides"][0]["minutes"] == 0
    await _json(client, "DELETE", f"/api/v1/availability/overrides/{tomorrow}")
    prefs = await _json(client, "GET", "/api/v1/planner/preferences")
    assert (
        prefs["rest_weekdays"] == [2]
        and prefs["session_minutes"] == PLANNER.allocation.session_minutes
    )


async def test_plain_english_availability_is_proposed_for_you_to_confirm(
    client: httpx.AsyncClient, fake_claude: FakeAnthropic
) -> None:
    fake_claude.respond = lambda _: {
        "text": json.dumps(
            {
                "weekdays": {
                    d: m
                    for d, m in zip(
                        [
                            "monday",
                            "tuesday",
                            "wednesday",
                            "thursday",
                            "friday",
                            "saturday",
                            "sunday",
                        ],
                        [180, 180, 180, 180, 180, 60, 60],
                        strict=True,
                    )
                },
                "dates": [
                    {"date": "2026-10-05", "minutes": 120},
                    {"date": "2020-01-01", "minutes": 5},
                ],
                "note": "Weekdays 3 hours, weekends 1 hour; 2 hours today.",
            }
        )
    }
    proposal = await _json(
        client,
        "POST",
        "/api/v1/availability/parse",
        json={"text": "3 hours every weekday but only 1 hour at weekends, and 2 hours today"},
    )
    assert proposal["weekdays"] == [180, 180, 180, 180, 180, 60, 60]
    assert proposal["dates"] == [{"day": "2026-10-05", "minutes": 120}]  # past dates dropped
    request = fake_claude.requests[-1]
    assert "Today is Monday 2026-10-05" in request["messages"][0]["content"][0]["text"]
    assert request["model"] == get_config().ai.models["haiku"].id
    # Nothing saved until you confirm.
    availability = await _json(client, "GET", "/api/v1/availability")
    assert availability["custom"] == [False] * 7


# --- "I have 45 minutes" ----------------------------------------------------------------------


async def test_i_have_45_minutes(
    client: httpx.AsyncClient, course: dict[str, Any], owner: User, db: AsyncSession
) -> None:
    """The phase's acceptance check: a sensible, explained session."""
    module, topics = course["module"], course["topics"]
    await _exam(client, module.id, 34)
    for n in range(12):
        db.add(
            Flashcard(
                id=uuid.uuid4(),
                user_id=owner.id,
                module_id=module.id,
                front_md=f"c{n}",
                back_md="b",
                origin="user",
                due=NOW - timedelta(hours=1),
            )
        )
    # Four sign errors in Integration this month: a recurring mistake.
    started = await _json(
        client,
        "POST",
        "/api/v1/quizzes",
        json={
            "module_id": str(module.id),
            "topic_ids": [str(topics["Integration"].id)],
            "count": 3,
        },
    )
    answers = (
        await db.scalars(
            select(QuestionAttempt).where(
                QuestionAttempt.quiz_attempt_id == uuid.UUID(started["attempt_id"])
            )
        )
    ).all()
    for answer in answers:
        answer.score, answer.marked_at, answer.marked_by = 0.0, NOW - timedelta(days=2), "rule"
        answer.mistake_category = "sign_error"
    await db.commit()

    built = await _json(client, "GET", "/api/v1/session-builder?minutes=45")
    blocks = built["blocks"]
    assert sum(b["minutes"] for b in blocks) == 45
    assert [b["kind"] for b in blocks][:2] == ["flashcards", "mistake_drill"]
    cards, drill, *topic_blocks = blocks
    assert cards["title"] == "Review 12 due flashcards" and cards["minutes"] <= 45 * 0.35
    assert drill["minutes"] == PLANNER.session_builder.mistake_drill_minutes
    assert "3 sign errors in Integration" in drill["reason"]
    weakest = topic_blocks[0]
    assert weakest["title"] == "Practise Integration"
    assert "est. 30%" in weakest["reason"] and "exam in 34 days" in weakest["reason"]
    assert weakest["action"]["to"] == "practice" and weakest["action"]["questions"] >= 3
    assert built["summary"].startswith("45 minutes: ")

    for bad in (5, 300):
        assert (await client.get(f"/api/v1/session-builder?minutes={bad}")).status_code == 422


async def test_the_assistant_plans_your_time(
    client: httpx.AsyncClient, course: dict[str, Any], fake_claude: FakeAnthropic
) -> None:
    await _exam(client, course["module"].id, 34)
    fake_claude.stream_script = [
        reply(tool_use("plan_session", {"minutes": 45})),
        reply(text("Here's a plan for your 45 minutes.")),
    ]
    conversation = (await client.post("/api/v1/conversations", json={})).json()["id"]
    await client.post(
        f"/api/v1/conversations/{conversation}/messages", json={"content": "I have 45 minutes"}
    )
    [result] = fake_claude.requests[1]["messages"][-1]["content"]
    assert result["content"].startswith("45 minutes: ")
    assert "Practise Integration" in result["content"] and "exam in 34 days" in result["content"]
    assert "Upcoming exams: MATH101 MATH101 final in 34 days" in result["content"]


# --- notifications ------------------------------------------------------------------------------


async def test_notifications_are_made_once_and_respect_settings(
    client: httpx.AsyncClient, course: dict[str, Any], owner: User, db: AsyncSession
) -> None:
    module = course["module"]
    await _exam(client, module.id, 7)
    for n in range(PLANNER.notifications.flashcards_due_threshold):
        db.add(
            Flashcard(
                id=uuid.uuid4(),
                user_id=owner.id,
                module_id=module.id,
                front_md=f"c{n}",
                back_md="b",
                origin="user",
                due=NOW - timedelta(hours=1),
            )
        )
    await db.commit()
    # 10 days without practice: past the neglected threshold.
    await db.execute(update(TopicMastery).values(last_practised_at=NOW - timedelta(days=10)))
    await db.commit()

    first = await _json(client, "GET", "/api/v1/notifications")
    kinds = sorted(n["kind"] for n in first["items"])
    assert kinds == ["exam", "flashcards", "neglected", "neglected", "neglected"]
    assert first["unread"] == 5
    exam = next(n for n in first["items"] if n["kind"] == "exam")
    assert exam["title"] == "Your MATH101 exam is in 7 days."
    again = await _json(client, "GET", "/api/v1/notifications")
    assert len(again["items"]) == 5  # each reminder only once

    await _json(client, "POST", f"/api/v1/notifications/{exam['id']}/read")
    assert (await _json(client, "GET", "/api/v1/notifications"))["unread"] == 4
    await _json(client, "POST", "/api/v1/notifications/read-all")
    assert (await _json(client, "GET", "/api/v1/notifications"))["unread"] == 0

    # The quiz reminder comes after its hour; off when switched off.
    await _json(client, "PATCH", "/api/v1/planner/preferences", json={"quiz_reminder_hour": 9})
    clock.freeze(NOW + timedelta(hours=1))
    items = (await _json(client, "GET", "/api/v1/notifications"))["items"]
    assert any(n["kind"] == "quiz" for n in items)
    await _json(
        client,
        "PATCH",
        "/api/v1/planner/preferences",
        json={"notify_flashcards": False, "quiet_from": 22, "quiet_to": 7},
    )
    clock.freeze(NOW + timedelta(days=1, hours=14))  # 23:00 in London: quiet
    before = len((await _json(client, "GET", "/api/v1/notifications"))["items"])
    clock.freeze(NOW + timedelta(days=2))
    after = [n["kind"] for n in (await _json(client, "GET", "/api/v1/notifications"))["items"]]
    assert len(after) > before and after.count("flashcards") == 1  # no new card reminder


# --- exams feed the daily quiz and flashcards -----------------------------------------------------


async def test_an_exam_raises_its_topics_in_the_daily_quiz(
    client: httpx.AsyncClient, owner: User, db: AsyncSession
) -> None:
    exam_module, exam_topics, year = await make_module(db, owner, "MATH101", ["Series"])
    other, other_topics, _ = await make_module(db, owner, "STAT101", ["Probability"], year)
    for module, topics in ((exam_module, exam_topics), (other, other_topics)):
        for topic in topics.values():
            await make_questions(db, owner, module, topic, 20)
    await _exam(client, exam_module.id, 3)
    plan = await _json(client, "GET", "/api/v1/daily-quiz/plan")
    by_title = {b["title"]: b for b in plan["buckets"]}
    assert by_title["Series"]["terms"]["urgency"] > 0.7
    assert by_title["Probability"]["terms"]["urgency"] == 0
    assert by_title["Series"]["allocated"] > by_title["Probability"]["allocated"]
    # Its length comes from today's availability (weekday default 120 min).
    reserve = PLANNER.reserve
    expected = min(
        max(round(120 * reserve.daily_quiz_fraction), reserve.daily_quiz_min_minutes),
        reserve.daily_quiz_max_minutes,
    )
    assert plan["minutes"] == expected


async def test_every_card_for_an_exam_is_seen_in_its_final_fortnight(
    client: httpx.AsyncClient, course: dict[str, Any], owner: User, db: AsyncSession
) -> None:
    module = course["module"]
    card = Flashcard(
        id=uuid.uuid4(),
        user_id=owner.id,
        module_id=module.id,
        front_md="Ratio test?",
        back_md="b",
        origin="user",
        fsrs_state=2,
        reps=3,
        stability=40.0,
        fsrs_difficulty=5.0,
        due=NOW + timedelta(days=40),
        last_review=NOW - timedelta(days=20),
    )
    db.add(card)
    await db.commit()
    assert (await _json(client, "GET", "/api/v1/flashcards/due"))["counts"]["due"] == 0
    await _exam(client, module.id, 10)
    due = await _json(client, "GET", "/api/v1/flashcards/due")
    assert [c["id"] for c in due["cards"]] == [str(card.id)]


async def test_exams_can_be_edited_and_deleted(
    client: httpx.AsyncClient, course: dict[str, Any], db: AsyncSession
) -> None:
    exam = await _exam(client, course["module"].id, 10)
    integration = course["topics"]["Integration"]
    edited = await _json(
        client,
        "PATCH",
        f"/api/v1/exams/{exam['id']}",
        json={"location": "Great Hall", "topic_ids": [str(integration.id)]},
    )
    assert edited["location"] == "Great Hall" and edited["topic_ids"] == [str(integration.id)]
    foreign = await db.scalar(select(Topic.id).where(Topic.id != integration.id))
    assert foreign is not None
    assert (await _json(client, "GET", f"/api/v1/exams?module_id={course['module'].id}"))[0][
        "id"
    ] == exam["id"]
    await _json(client, "DELETE", f"/api/v1/exams/{exam['id']}")
    plan = await _json(client, "GET", "/api/v1/plan")
    assert not plan["exams"] and not any(s["kind"] == "mock_exam" for s in plan["upcoming"])


async def test_what_to_study_next_is_explained(
    client: httpx.AsyncClient, course: dict[str, Any], owner: User, db: AsyncSession
) -> None:
    module = course["module"]
    await _exam(client, module.id, 34)
    for n in range(PLANNER.notifications.flashcards_due_threshold):
        db.add(
            Flashcard(
                id=uuid.uuid4(),
                user_id=owner.id,
                module_id=module.id,
                front_md=f"c{n}",
                back_md="b",
                origin="user",
                due=NOW - timedelta(hours=1),
            )
        )
    await db.commit()
    first, *topics = await _json(client, "GET", "/api/v1/recommendations?limit=3")
    assert first["kind"] == "flashcards" and "10 cards are due" in first["reason"]
    assert [t["title"] for t in topics] == ["Integration", "Series"]
    assert topics[0]["reason"].startswith("est. 30%") and "exam in 34 days" in topics[0]["reason"]
    assert topics[0]["action"]["to"] == "practice"


async def test_topic_importance_shifts_the_plan(
    client: httpx.AsyncClient, course: dict[str, Any], db: AsyncSession
) -> None:
    """Two topics of equal strength: the one marked important gets more time."""
    topics = course["topics"]
    await db.execute(
        update(TopicMastery)
        .where(TopicMastery.topic_id.in_([topics["Series"].id, topics["Limits"].id]))
        .values(strength=0.5)
    )
    await db.execute(update(Topic).where(Topic.id == topics["Limits"].id).values(importance=5))
    await db.commit()
    await _exam(client, course["module"].id, 21)
    plan = await _json(client, "GET", "/api/v1/plan")
    minutes: dict[str, int] = {}
    for s in plan["today"] + plan["upcoming"]:
        if s["kind"] == "topic":
            minutes[s["title"]] = minutes.get(s["title"], 0) + s["minutes"]
    assert minutes["Limits"] > minutes["Series"]
    limits = next(s for s in plan["today"] + plan["upcoming"] if s["title"] == "Limits")
    assert "importance 5/5" in limits["reason"]
