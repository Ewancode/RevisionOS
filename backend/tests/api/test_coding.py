"""Coding practice: exercises, browser-reported submissions, the hint ladder
(enforced by the server) and Claude-generated exercises as drafts."""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import ClaudeClient
from app.core.config import get_config
from app.models import CodingExercise, QuestionAttempt, User
from app.practice.generation import run_draft
from app.retrieval.embeddings import HashingProvider
from tests.fakes import FakeAnthropic
from tests.learning_support import make_module, make_questions
from tests.support import make_user, signed_in

pytestmark = pytest.mark.db

SECRET = "return sorted(xs)[len(xs) // 2]  # the reference solution"
EXERCISE = {
    "language": "python",
    "title": "Median of a list",
    "prompt_md": "Write `median(xs)` returning the middle value of an odd-length list.",
    "starter_code": "def median(xs):\n    pass\n",
    "solution_code": f"def median(xs):\n    {SECRET}\n",
    "tests": [
        {"name": "odd list", "code": "assert median([3, 1, 2]) == 2", "hidden": False},
        {"name": "single item", "code": "assert median([7]) == 7", "hidden": True},
    ],
    "difficulty": "easy",
}


@pytest.fixture
async def owner(db: AsyncSession) -> User:
    return await make_user(db)


@pytest.fixture
async def client(db_app: FastAPI, owner: User) -> AsyncIterator[httpx.AsyncClient]:
    async with signed_in(db_app, owner) as c:
        yield c


@pytest.fixture
async def module_id(owner: User, db: AsyncSession) -> str:
    module, _, _ = await make_module(db, owner, "MATH163", ["Data"])
    return str(module.id)


async def _ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json() if response.content else None


async def _exercise(client: httpx.AsyncClient, module_id: str, **changes: Any) -> dict[str, Any]:
    body = {**EXERCISE, "module_id": module_id, **changes}
    return dict(await _ok(await client.post("/api/v1/coding/exercises", json=body), 201))


def _passing(exercise: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"name": t["name"], "passed": True, "message": ""} for t in exercise["tests"]]


def tutor_says(text: str):  # type: ignore[no-untyped-def]
    return lambda _request: {"text": text}


# --- exercises ------------------------------------------------------------------------------


async def test_an_exercise_never_sends_its_solution(
    client: httpx.AsyncClient, module_id: str
) -> None:
    exercise = await _exercise(client, module_id)
    assert "solution_code" not in exercise and SECRET not in json.dumps(exercise)
    # Hidden tests go to the browser (they run there); the page hides them.
    assert [t["hidden"] for t in exercise["tests"]] == [False, True]
    assert exercise["progress"] == {
        "submissions": 0,
        "best_passed": None,
        "total": 2,
        "solved": False,
    }
    listed = await _ok(await client.get(f"/api/v1/coding/exercises?module_id={module_id}"))
    assert [e["title"] for e in listed] == ["Median of a list"]
    config = await _ok(await client.get("/api/v1/coding/config"))
    # The runtimes come from this origin; only their packages from elsewhere.
    python, r = config["runtimes"]["python"], config["runtimes"]["r"]
    assert python["base_url"].startswith("/runtimes/pyodide/")
    assert python["package_url"].startswith("https://cdn.jsdelivr.net/pyodide/")
    assert r["base_url"].startswith("/runtimes/webr/")
    assert r["package_url"] == "https://repo.r-wasm.org/"


async def test_exercises_are_checked_without_running_them(
    client: httpx.AsyncClient, module_id: str
) -> None:
    body = {**EXERCISE, "module_id": module_id}
    bad = await client.post(
        "/api/v1/coding/exercises",
        json={
            **body,
            "solution_code": "def median(xs)\n    return 1\n",
            "tests": [{"name": "a", "code": "assert median([1]) == 1", "hidden": True}],
        },
    )
    assert bad.status_code == 422
    message = bad.json()["error"]["message"]
    assert "The reference solution has a Python syntax error on line 1" in message
    assert "At least one test must be visible" in message
    # R is not parsed on the server; it still needs its shape.
    r = await _exercise(
        client, module_id, language="r", starter_code="median2 <- function(x) stop('todo')",
        solution_code="median2 <- function(x) median(x)",
        tests=[{"name": "odd", "code": "stopifnot(median2(c(3, 1, 2)) == 2)", "hidden": False}],
        packages=["dplyr"],
    )  # fmt: skip
    assert r["language"] == "r" and r["packages"] == ["dplyr"]


async def test_editing_and_deleting(client: httpx.AsyncClient, module_id: str) -> None:
    exercise = await _exercise(client, module_id)
    path = f"/api/v1/coding/exercises/{exercise['id']}"
    edited = await _ok(await client.patch(path, json={"title": "Median", "assessed": True}))
    assert edited["title"] == "Median" and edited["assessed"]
    same = await client.patch(path, json={"starter_code": EXERCISE["solution_code"]})
    assert same.status_code == 422 and "already the solution" in same.text
    await _ok(await client.delete(path), 204)
    assert (await client.get(path)).status_code == 404
    await _ok(await client.post(f"{path}/restore"))
    assert (await client.get(path)).status_code == 200


# --- submissions ----------------------------------------------------------------------------


async def test_submissions_record_the_browsers_results(
    client: httpx.AsyncClient, module_id: str
) -> None:
    exercise = await _exercise(client, module_id)
    path = f"/api/v1/coding/exercises/{exercise['id']}/submissions"
    # Results must name exactly this exercise's tests, in order.
    forged = await client.post(
        path, json={"code": "x", "results": [{"name": "odd list", "passed": True}]}
    )
    assert forged.status_code == 422 and forged.json()["error"]["code"] == "results_mismatch"

    first = await _ok(
        await client.post(
            path,
            json={
                "code": "def median(xs):\n    return xs[0]\n",
                "results": [
                    {"name": "odd list", "passed": False, "message": "AssertionError"},
                    {"name": "single item", "passed": True},
                ],
                "runtime_ms": 40,
            },
        ),
        201,
    )
    assert (first["passed"], first["total"]) == (1, 2)
    await _ok(await client.post(path, json={"code": "solved", "results": _passing(exercise)}), 201)
    again = await _ok(await client.get(f"/api/v1/coding/exercises/{exercise['id']}"))
    assert again["progress"] == {"submissions": 2, "best_passed": 2, "total": 2, "solved": True}
    assert again["latest_code"] == "solved"
    history = await _ok(await client.get(path))
    assert [s["passed"] for s in history] == [2, 1]


# --- the hint ladder ------------------------------------------------------------------------


async def test_the_hint_ladder_climbs_one_rung_at_a_time(
    client: httpx.AsyncClient, module_id: str, fake_claude: FakeAnthropic
) -> None:
    exercise = await _exercise(client, module_id)
    hints = f"/api/v1/coding/exercises/{exercise['id']}/hints"
    state = await _ok(await client.get(hints))
    assert state["next_level"] == 1 and state["next_label"] == "Guiding question"
    assert state["locked_reason"] == "The full solution unlocks after you submit an attempt."

    for level in (1, 2, 3, 4):
        fake_claude.respond = tutor_says(f"Rung {level} help.")
        state = await _ok(
            await client.post(
                hints,
                json={"work": "def median(xs):\n    return xs[0]\n", "results": "odd list: failed"},
            )
        )
        assert [h["level"] for h in state["hints"]] == list(range(1, level + 1))
        sent = fake_claude.requests[-1]
        text = sent["messages"][0]["content"][0]["text"]
        assert text.startswith(f"Rung {level} of the hint ladder")
        assert "return xs[0]" in text and "odd list: failed" in text
        # The reference solution and hidden tests never reach Claude.
        assert SECRET not in json.dumps(sent) and "median([7])" not in json.dumps(sent)
        assert sent["model"] == get_config().ai.models["sonnet"].id
    assert "Rung 3 help." in text  # earlier hints are sent back for continuity
    assert state["next_level"] is None

    stuck = await client.post(hints, json={})
    assert stuck.status_code == 409 and "after you submit" in stuck.json()["error"]["message"]

    # After an attempt, rung 5 is the stored solution: no AI call.
    await client.post(
        f"/api/v1/coding/exercises/{exercise['id']}/submissions",
        json={
            "code": "x",
            "results": [
                {"name": "odd list", "passed": False},
                {"name": "single item", "passed": False},
            ],
        },
    )
    calls = len(fake_claude.requests)
    state = await _ok(await client.post(hints, json={}))
    assert len(fake_claude.requests) == calls
    solution = state["hints"][-1]
    assert solution["level"] == 5 and solution["label"] == "Full solution"
    assert SECRET in solution["content_md"]
    assert state["next_level"] is None and state["locked_reason"] is None


async def test_assessed_work_never_reveals_the_solution(
    client: httpx.AsyncClient, module_id: str, fake_claude: FakeAnthropic
) -> None:
    exercise = await _exercise(client, module_id, assessed=True)
    base = f"/api/v1/coding/exercises/{exercise['id']}"
    await client.post(f"{base}/submissions", json={"code": "x", "results": _passing(exercise)})
    fake_claude.respond = tutor_says("A hint.")
    for _ in range(4):
        await _ok(await client.post(f"{base}/hints", json={}))
    final = await client.post(f"{base}/hints", json={})
    assert final.status_code == 409 and "never the solution" in final.json()["error"]["message"]


async def test_question_hints_during_a_practice_quiz(
    client: httpx.AsyncClient, owner: User, db: AsyncSession, fake_claude: FakeAnthropic
) -> None:
    module, topics, _ = await make_module(db, owner, "MATH101", ["Series"])
    [question] = await make_questions(db, owner, module, topics["Series"], 1)
    started = await _ok(
        await client.post("/api/v1/quizzes", json={"module_id": str(module.id), "count": 1}), 201
    )
    hints = f"/api/v1/attempts/{started['attempt_id']}/responses/{question.id}/hints"
    fake_claude.respond = tutor_says("Which option is a definition?")
    state = await _ok(await client.post(hints, json={"work": "I think wrong"}))
    assert state["hints"][0]["content_md"] == "Which option is a definition?"
    text = fake_claude.requests[-1]["messages"][0]["content"][0]["text"]
    assert "- right\n- wrong" in text and "I think wrong" in text
    # The answer key is never sent.
    assert '"correct"' not in json.dumps(fake_claude.requests[-1])
    used = await db.scalar(
        select(QuestionAttempt.hints_used).where(QuestionAttempt.question_id == question.id)
    )
    assert used == 1
    for _ in range(3):
        await client.post(hints, json={})
    state = await _ok(await client.get(hints))
    assert state["next_level"] is None and state["top"] == 4

    await client.post(f"/api/v1/attempts/{started['attempt_id']}/submit")
    assert (await client.post(hints, json={})).status_code in (409,)


async def test_no_hints_while_a_mock_exam_is_open(
    client: httpx.AsyncClient, module_id: str, owner: User, db: AsyncSession
) -> None:
    exercise = await _exercise(client, module_id)
    module = uuid.UUID(module_id)
    from app.models import Module

    m = await db.get(Module, module)
    assert m is not None
    await make_questions(db, owner, m, None, 2)
    await _ok(
        await client.post(
            "/api/v1/quizzes", json={"module_id": module_id, "kind": "mock", "count": 2}
        ),
        201,
    )
    blocked = await client.post(f"/api/v1/coding/exercises/{exercise['id']}/hints", json={})
    assert blocked.status_code == 423


# --- Claude's exercises, as drafts -------------------------------------------------------------


def generated(**changes: Any) -> dict[str, Any]:
    return {**EXERCISE, "packages": [], "sources": [], **changes}


async def test_generated_exercises_are_checked_previewed_and_saved(
    client: httpx.AsyncClient,
    module_id: str,
    db: AsyncSession,
    claude: ClaudeClient,
    fake_claude: FakeAnthropic,
) -> None:
    draft = await _ok(
        await client.post(
            "/api/v1/drafts",
            json={"module_id": module_id, "kind": "coding", "language": "python", "count": 2,
                  "instructions": "statistics in pandas"},
        ),
        202,
    )  # fmt: skip
    broken = generated(title="Broken", solution_code="def median(xs)\n  pass\n")
    replies = iter(
        [
            {"text": json.dumps({"items": [generated(), broken]})},
            {"text": json.dumps({"items": [generated(title="Repaired", language="r", tests=[
                {"name": "odd", "code": "stopifnot(TRUE)", "hidden": False}])]})},
        ]
    )  # fmt: skip
    fake_claude.respond = lambda _: next(replies)
    embedder = HashingProvider(get_config().retrieval.embeddings.dimensions)
    await run_draft(db, claude, embedder, get_config(), uuid.UUID(draft["id"]))

    ready = await _ok(await client.get(f"/api/v1/drafts/{draft['id']}"))
    assert ready["status"] == "ready"
    good, bad = ready["payload"]["items"]
    assert good["valid"] and good["solution_code"]  # the preview runs it in the browser
    # The repair came back in the wrong language, no better, so the original stays.
    assert not bad["valid"] and "Python syntax error" in bad["problems"][0]
    first = fake_claude.requests[0]
    assert first["model"] == get_config().ai.models["sonnet"].id
    assert "Write 2 coding exercises in Python" in first["messages"][0]["content"][0]["text"]

    refused = await client.post(f"/api/v1/drafts/{draft['id']}/save", json={"selected": [1]})
    assert refused.status_code == 422
    saved = await _ok(
        await client.post(f"/api/v1/drafts/{draft['id']}/save", json={"selected": [0]})
    )
    assert saved["saved_items"] == 1
    exercise = await db.scalar(
        select(CodingExercise).where(CodingExercise.module_id == uuid.UUID(module_id))
    )
    assert exercise is not None and exercise.origin == "claude" and SECRET in exercise.solution_code

    wrong = await client.post(
        "/api/v1/drafts", json={"module_id": module_id, "kind": "questions", "language": "r"}
    )
    assert wrong.status_code == 422
