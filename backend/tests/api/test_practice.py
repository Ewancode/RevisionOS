"""Phase 6 end to end with a scripted Claude: drafts (questions, flashcards,
materials), validation and repair, saving, versions, quizzes, marking of
every answer type, explanations, disputes, overrides, mock exams and photos."""

import io
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import anthropic
import httpx
import pytest
from fastapi import FastAPI
from PIL import Image
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.ingestion.pipeline import Deps
from app.models import AIInteraction, QuizAttempt, User
from app.practice.generation import run_draft
from app.practice.marking import mark_attempt
from tests import factories
from tests.fakes import FakeAnthropic, RecordingQueue, cite, text
from tests.support import create_module, ingest, make_user, signed_in

pytestmark = pytest.mark.db

AI = get_config().ai
LECTURE = [
    "Black-Scholes assumptions: the underlying follows geometric Brownian motion, "
    "volatility and the risk-free rate are constant, and there are no dividends.",
    "Integration by parts follows from the product rule for derivatives.",
    "The Central Limit Theorem says sample means are approximately normal.",
]
NULLS = dict.fromkeys(
    [
        "options",
        "correct_option",
        "true_or_false",
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
)


def item(type_: str, stem: str, **fields: Any) -> dict[str, Any]:
    return {
        "type": type_,
        "difficulty": "easy",
        "stem_md": stem,
        "solution_md": "Worked solution.",
        "sources": [1],
        **NULLS,
        **fields,
    }


MC = item(
    "multiple_choice",
    "Which is a Black-Scholes assumption?",
    options=["Constant volatility", "Jumps", "Dividends"],
    correct_option=0,
)


class ScriptedClaude:
    """Answers each kind of request the way Claude would, from queued scripts."""

    def __init__(self) -> None:
        self.questions: list[list[dict[str, Any]]] = []
        self.flashcards: list[list[dict[str, Any]]] = []
        # (text in the question, the mark Claude gives), each used once.
        self.marks: list[tuple[str, dict[str, Any]]] = []
        self.explained: list[str] = []

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        system = request["system"] if isinstance(request["system"], str) else ""
        if system.startswith("You write practice questions"):
            return {"text": json.dumps({"items": self.questions.pop(0)})}
        if system.startswith("You write flashcards"):
            return {"text": json.dumps({"items": self.flashcards.pop(0)})}
        if system.startswith("You write revision materials"):
            blocks = request["messages"][0]["content"]
            first = next(b for b in blocks if b["type"] == "search_result")
            return {
                "blocks": [
                    text(
                        "# Black-Scholes — Revision Guide\n\nVolatility is constant.",
                        cite(0, first["source"], "assumptions"),
                    ),
                    text("\n\nRemember the assumptions."),
                ]
            }
        if system.startswith("You mark"):
            body = request["messages"][0]["content"][0]["text"]
            index = next(i for i, (key, _) in enumerate(self.marks) if key in body)
            return {"text": json.dumps(self.marks.pop(index)[1])}
        if system.startswith("A university student"):
            body = request["messages"][0]["content"][0]["text"]
            count = body.count("Item ")
            self.explained.append(body)
            return {
                "text": json.dumps(
                    {
                        "items": [
                            {
                                "item": i,
                                "why_wrong": f"why {i}",
                                "correct_answer": "c",
                                "reasoning": "r",
                                "mistake": "m",
                                "how_to_avoid": "h",
                                "mistake_category": "concept_confusion",
                            }
                            for i in range(1, count + 1)
                        ]
                    }
                )
            }
        if system.startswith("You transcribe"):
            return {
                "text": json.dumps(
                    {"markdown": "$$f'(x) = 2x$$", "confidence": "high", "notes": ""}
                )
            }
        raise AssertionError(f"unexpected request: {system[:60]}")


@pytest.fixture
def scripted(fake_claude: FakeAnthropic) -> ScriptedClaude:
    script = ScriptedClaude()
    fake_claude.respond = script
    return script


@pytest.fixture
async def owner(db: AsyncSession) -> User:
    return await make_user(db)


@pytest.fixture
async def client(db_app: FastAPI, owner: User) -> AsyncIterator[httpx.AsyncClient]:
    async with signed_in(db_app, owner) as c:
        yield c


@pytest.fixture
async def course(
    client: httpx.AsyncClient, deps: Deps, queue: RecordingQueue, tmp_path: Path
) -> dict[str, str]:
    module = await create_module(client)
    doc = await ingest(
        client, deps, queue, module["id"], factories.pdf(tmp_path / "l.pdf", LECTURE), "Week 3.pdf"
    )
    return {"module": module["id"], "document": doc}


async def run_jobs(queue: RecordingQueue, deps: Deps) -> list[str]:
    """Run queued generation and marking jobs in-process, as the worker would."""
    ran = []
    while queue.jobs:
        name, args = queue.jobs.pop(0)
        async with deps.sessions() as db:
            if name == "generate_draft":
                await run_draft(db, deps.claude, deps.embedder, deps.config, uuid.UUID(args[0]))
            elif name == "mark_attempt":
                await mark_attempt(db, deps.claude, deps.config, uuid.UUID(args[0]))
        ran.append(name)
    return ran


async def _draft(client: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/drafts", json=body)
    assert response.status_code == 202, response.text
    return dict(response.json())


async def _get(client: httpx.AsyncClient, path: str) -> Any:
    response = await client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


# --- questions -----------------------------------------------------------------------------------


async def test_generated_questions_are_checked_repaired_and_saved(
    client: httpx.AsyncClient,
    course: dict[str, str],
    scripted: ScriptedClaude,
    fake_claude: FakeAnthropic,
    queue: RecordingQueue,
    deps: Deps,
) -> None:
    wrong_check = item(
        "numerical",
        "What is $\\int_0^3 t^2\\,dt$?",
        value=10,
        tolerance=0.01,
        check="integrate(t**2, (t, 0, 3))",
    )
    ungrounded = item("true_false", "Volatility is constant.", true_or_false=True, sources=[99])
    scripted.questions = [
        [MC, wrong_check, ungrounded],
        # The repair: the numerical one is fixed; the other is still wrong.
        [{**wrong_check, "value": 9}, ungrounded],
    ]
    draft = await _draft(client, module_id=course["module"], kind="questions", count=3)
    assert draft["status"] == "generating"
    assert await run_jobs(queue, deps) == ["generate_draft"]

    draft = await _get(client, f"/api/v1/drafts/{draft['id']}")
    assert draft["status"] == "ready", draft["error_code"]
    items = draft["payload"]["items"]
    assert [i["valid"] for i in items] == [True, True, False]
    assert items[1].get("repaired") is True
    assert "not supplied" in items[2]["problems"][0]
    assert "embedding" not in items[0]
    # First call on the cheap model; the repair on its stronger escalation.
    first, repair = fake_claude.requests
    assert first["model"] == AI.models["haiku"].id and "output_config" in first
    assert repair["model"] == AI.models["sonnet"].id
    assert repair["output_config"]["effort"] == "medium"
    assert '"problems"' in repair["messages"][0]["content"][0]["text"]

    refused = await client.post(f"/api/v1/drafts/{draft['id']}/save", json={"selected": [2]})
    assert refused.status_code == 422
    saved = await client.post(f"/api/v1/drafts/{draft['id']}/save", json={})
    assert saved.status_code == 200 and saved.json()["saved_items"] == 2
    again = await client.post(f"/api/v1/drafts/{draft['id']}/save", json={})
    assert again.status_code == 409

    bank = await _get(client, f"/api/v1/questions?module_id={course['module']}")
    assert {q["type"] for q in bank} == {"multiple_choice", "numerical"}
    numerical = next(q for q in bank if q["type"] == "numerical")
    assert numerical["answer_spec"]["value"] == 9
    [source] = numerical["sources"]
    assert source["document_id"] == course["document"] and source["page_no"] in (1, 2, 3)
    assert source["filename"] == "Week 3.pdf" and source["source_tier"] == "university"
    assert all(q["origin"] == "claude" and q["attempts"] == 0 for q in bank)


async def test_near_duplicates_of_the_bank_are_rejected(
    client: httpx.AsyncClient,
    course: dict[str, str],
    scripted: ScriptedClaude,
    queue: RecordingQueue,
    deps: Deps,
) -> None:
    scripted.questions = [[MC], [MC, {**MC}]]
    first = await _draft(client, module_id=course["module"], kind="questions", count=1)
    await run_jobs(queue, deps)
    await client.post(f"/api/v1/drafts/{first['id']}/save", json={})

    second = await _draft(client, module_id=course["module"], kind="questions", count=2)
    await run_jobs(queue, deps)
    items = (await _get(client, f"/api/v1/drafts/{second['id']}"))["payload"]["items"]
    assert "already saved" in items[0]["problems"][0]
    assert not items[1]["valid"]


async def test_a_failed_generation_can_be_regenerated_or_discarded(
    client: httpx.AsyncClient,
    owner: User,
    db: AsyncSession,
    scripted: ScriptedClaude,
    queue: RecordingQueue,
    deps: Deps,
) -> None:
    module = await create_module(client, "MATH111")  # no files: nothing to write from
    draft = await _draft(client, module_id=module["id"], kind="questions")
    await run_jobs(queue, deps)
    failed = await _get(client, f"/api/v1/drafts/{draft['id']}")
    assert failed["status"] == "failed" and failed["error_code"] == "no_material"

    again = await client.post(
        f"/api/v1/drafts/{draft['id']}/regenerate", json={"instructions": "focus on series"}
    )
    assert again.status_code == 202 and again.json()["request"]["instructions"] == "focus on series"
    assert queue.jobs[0][0] == "generate_draft"
    discarded = await client.post(f"/api/v1/drafts/{draft['id']}/discard")
    assert discarded.json()["status"] == "discarded"
    assert await _get(client, f"/api/v1/drafts?module_id={module['id']}") == []


# --- flashcards -------------------------------------------------------------------------------


async def test_flashcards_generate_save_edit_and_trash(
    client: httpx.AsyncClient,
    course: dict[str, str],
    scripted: ScriptedClaude,
    queue: RecordingQueue,
    deps: Deps,
) -> None:
    scripted.flashcards = [
        [
            {"front_md": "State the CLT.", "back_md": "Means are approx. normal.", "sources": [1]},
            {"front_md": "Unclosed $x", "back_md": "y", "sources": [1]},
        ],
        # The repair round: still broken.
        [{"front_md": "Still $unclosed", "back_md": "y", "sources": [1]}],
    ]
    draft = await _draft(client, module_id=course["module"], kind="flashcards")
    await run_jobs(queue, deps)
    payload = (await _get(client, f"/api/v1/drafts/{draft['id']}"))["payload"]
    assert [i["valid"] for i in payload["items"]] == [True, False]
    await client.post(f"/api/v1/drafts/{draft['id']}/save", json={})

    mine = await client.post(
        "/api/v1/flashcards",
        json={"module_id": course["module"], "front_md": "What is $e^{i\\pi}$?", "back_md": "$-1$"},
    )
    assert mine.status_code == 201 and mine.json()["origin"] == "user"
    cards = await _get(client, f"/api/v1/flashcards?module_id={course['module']}")
    assert [c["front_md"] for c in cards] == ["State the CLT.", "What is $e^{i\\pi}$?"]

    card = cards[0]["id"]
    edited = await client.patch(f"/api/v1/flashcards/{card}", json={"back_md": "Normal."})
    assert edited.json()["back_md"] == "Normal."
    assert (await client.delete(f"/api/v1/flashcards/{card}")).status_code == 204
    trash = await _get(client, "/api/v1/trash")
    assert [c["id"] for c in trash["flashcards"]] == [card]
    assert (await client.post(f"/api/v1/flashcards/{card}/restore")).status_code == 200


# --- materials and versions -------------------------------------------------------------------


async def test_generated_material_cites_its_pages_and_keeps_every_version(
    client: httpx.AsyncClient,
    course: dict[str, str],
    scripted: ScriptedClaude,
    fake_claude: FakeAnthropic,
    queue: RecordingQueue,
    deps: Deps,
) -> None:
    draft = await _draft(client, module_id=course["module"], kind="material")
    await run_jobs(queue, deps)
    draft = await _get(client, f"/api/v1/drafts/{draft['id']}")
    payload = draft["payload"]
    assert payload["title"] == "Black-Scholes — Revision Guide"
    assert "Volatility is constant. [[1]](#cite-1)" in payload["content_md"]
    assert payload["citations"][0]["filename"] == "Week 3.pdf"
    request = fake_claude.requests[-1]
    assert request["model"] == AI.models["sonnet"].id and "output_config" in request
    assert request["max_tokens"] == AI.routing["revision_guide"].max_tokens

    saved = (await client.post(f"/api/v1/drafts/{draft['id']}/save", json={})).json()
    material_id = saved["material_id"]
    material = await _get(client, f"/api/v1/materials/{material_id}")
    assert material["origin"] == "claude" and material["kind"] == "guide"
    assert material["current"]["created_by"] == "claude"
    assert material["current"]["citations"][0]["filename"] == "Week 3.pdf"
    v1 = material["current"]["id"]

    # Your edit is a new version; the old one stays.
    edited = await client.post(
        f"/api/v1/materials/{material_id}/versions",
        json={"content_md": "# Black-Scholes\n\nMy own words.", "change_note": "Rewrote"},
    )
    v2 = edited.json()["current"]["id"]
    assert [v["version_no"] for v in edited.json()["versions"]] == [2, 1]
    diff = await _get(
        client, f"/api/v1/materials/{material_id}/diff?from_version={v1}&to_version={v2}"
    )
    assert {"op": "insert", "text": "My own words."} in diff["lines"]
    assert any(line["op"] == "delete" for line in diff["lines"])

    restored = (await client.post(f"/api/v1/materials/{material_id}/versions/{v1}/restore")).json()
    assert restored["current"]["version_no"] == 3
    assert restored["current"]["change_note"] == "Restored version 1"
    current = restored["current"]["id"]
    blocked = await client.delete(f"/api/v1/materials/{material_id}/versions/{current}")
    assert blocked.status_code == 409
    assert (
        await client.delete(f"/api/v1/materials/{material_id}/versions/{v2}")
    ).status_code == 204

    # Claude's improvement is a new version too; nothing is overwritten.
    improve = await _draft(
        client, module_id=course["module"], kind="material", improve_material_id=material_id
    )
    await run_jobs(queue, deps)
    assert "<existing_material>" in fake_claude.requests[-1]["messages"][0]["content"][-1]["text"]
    await client.post(f"/api/v1/drafts/{improve['id']}/save", json={})
    material = await _get(client, f"/api/v1/materials/{material_id}")
    assert [v["version_no"] for v in material["versions"]] == [4, 3, 1]
    assert material["current"]["change_note"] == "Improved by Claude"

    assert (await client.delete(f"/api/v1/materials/{material_id}")).status_code == 204
    trash = await _get(client, "/api/v1/trash")
    assert [m["id"] for m in trash["materials"]] == [material_id]
    assert (await client.post(f"/api/v1/materials/{material_id}/restore")).status_code == 200


async def test_your_own_material_starts_at_version_one(
    client: httpx.AsyncClient, course: dict[str, str]
) -> None:
    created = await client.post(
        "/api/v1/materials",
        json={"module_id": course["module"], "title": "My notes", "content_md": "# Notes\n\n$x$"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["origin"] == "user" and body["current"]["version_no"] == 1
    listed = await _get(client, f"/api/v1/materials?module_id={course['module']}")
    assert [m["title"] for m in listed] == ["My notes"]


# --- quizzes and marking --------------------------------------------------------------------------

EVERY_TYPE = [
    MC,
    item("true_false", "Volatility varies in Black-Scholes.", true_or_false=False),
    item(
        "numerical",
        "$P(X=3)$ for $X \\sim B(10, 1/2)$, to 4 d.p.?",
        value=0.1172,
        tolerance=0.00005,
        check="binomial(10,3)*Rational(1,2)**10",
    ),
    item(
        "expression", "Differentiate $x^2 e^x$.", expression="exp(x)*(x**2 + 2*x)", variables=["x"]
    ),
    item(
        "short_answer",
        "Which theorem says sample means are approximately normal?",
        accepted_answers=["Central Limit Theorem", "CLT"],
    ),
    item(
        "explanation",
        "Why must volatility be constant in Black-Scholes?",
        rubric=[{"point": "Closed form needs it", "marks": 2}],
        model_answer="SECRET-MODEL: the closed-form solution of the PDE assumes it.",
    ),
    item(
        "derivation",
        "Derive integration by parts.",
        rubric=[
            {"point": "Product rule", "marks": 1},
            {"point": "Integrate", "marks": 1},
            {"point": "Rearrange", "marks": 1},
        ],
        model_answer="SECRET-PROOF: differentiate uv, integrate both sides, rearrange.",
    ),
]


async def _bank(
    client: httpx.AsyncClient,
    course: dict[str, str],
    scripted: ScriptedClaude,
    queue: RecordingQueue,
    deps: Deps,
) -> dict[str, str]:
    """One saved question of every type; returns {type: id}."""
    scripted.questions = [
        [{**q, "stem_md": f"{q['stem_md']} ({n})"} for n, q in enumerate(EVERY_TYPE)]
    ]
    draft = await _draft(client, module_id=course["module"], kind="questions", count=7)
    await run_jobs(queue, deps)
    saved = await client.post(f"/api/v1/drafts/{draft['id']}/save", json={})
    assert saved.json()["saved_items"] == 7, await _get(client, f"/api/v1/drafts/{draft['id']}")
    bank = await _get(client, f"/api/v1/questions?module_id={course['module']}")
    return {q["type"]: q["id"] for q in bank}


ANSWERS = {
    "multiple_choice": {"choice": 0},
    "true_false": {"answer": True},  # wrong
    "numerical": {"value": "15/128"},
    "expression": {"expression": "e^x (x^2 + 2x)"},
    "short_answer": {"text": "the central limit theorem."},  # not exact: Claude decides
    "explanation": {"text": "Because the PDE needs it."},
    "derivation": {"text": "(uv)' = u'v + uv', integrate."},
}


def mark(awarded: list[float], confidence: str = "high", **extra: Any) -> dict[str, Any]:
    return {
        "points": [{"awarded": a, "comment": "ok"} for a in awarded],
        "feedback": "Reasonable.",
        "confidence": confidence,
        "explanation": None,
        "mistake_category": None,
        **extra,
    }


async def _start(
    client: httpx.AsyncClient, course: dict[str, str], ids: list[str], **body: Any
) -> str:
    response = await client.post(
        "/api/v1/quizzes", json={"module_id": course["module"], "question_ids": ids, **body}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["attempt_id"])


async def test_a_quiz_marks_every_answer_type(
    client: httpx.AsyncClient,
    course: dict[str, str],
    scripted: ScriptedClaude,
    fake_claude: FakeAnthropic,
    queue: RecordingQueue,
    deps: Deps,
) -> None:
    ids = await _bank(client, course, scripted, queue, deps)
    attempt = await _start(client, course, list(ids.values()))

    # Answering: the answers are never sent before submission.
    before = await client.get(f"/api/v1/attempts/{attempt}")
    assert "SECRET" not in before.text and "correct_option" not in before.text
    items = before.json()["items"]
    assert all(i["score"] is None and i["solution_md"] is None for i in items)
    by_type = {i["type"]: i for i in items}
    assert by_type["multiple_choice"]["view"]["options"][0] == "Constant volatility"
    assert by_type["derivation"]["view"] == {"marks": 3}
    bad = await client.put(
        f"/api/v1/attempts/{attempt}/responses/{ids['numerical']}", json={"response": {"choice": 1}}
    )
    assert bad.status_code == 422
    for type_, response in ANSWERS.items():
        saved = await client.put(
            f"/api/v1/attempts/{attempt}/responses/{ids[type_]}",
            json={"response": response, "time_ms": 30_000, "self_confidence": 3},
        )
        assert saved.status_code == 204, saved.text

    submitted = (await client.post(f"/api/v1/attempts/{attempt}/submit")).json()
    assert submitted["status"] == "marking"
    exact = {i["type"]: i["score"] for i in submitted["items"]}
    assert exact == {
        "multiple_choice": 1.0,
        "true_false": 0.0,
        "numerical": 1.0,
        "expression": 1.0,
        "short_answer": None,
        "explanation": None,
        "derivation": None,
    }
    assert queue.jobs == [("mark_attempt", (attempt,))]
    assert (await client.post(f"/api/v1/attempts/{attempt}/submit")).status_code == 409

    explanation = {
        "why_wrong": "No integration step.",
        "correct_answer": "c",
        "reasoning": "r",
        "mistake": "Stopped early",
        "how_to_avoid": "h",
    }
    scripted.marks = [
        ("Which theorem", mark([1])),
        ("Why must volatility", mark([1], confidence="low")),  # unsure, so...
        ("Why must volatility", mark([2])),  # ...re-marked on the stronger model
        (
            "Derive integration",
            mark([1, 0, 0], explanation=explanation, mistake_category="incomplete_justification"),
        ),
    ]
    before_marking = len(fake_claude.requests)
    await run_jobs(queue, deps)
    marking = fake_claude.requests[before_marking:]

    def about(request: dict[str, Any]) -> str:
        body = request["messages"][0]["content"][0]["text"]
        keys = ("Which theorem", "Why must volatility", "Derive integration", "Volatility varies")
        return next(k for k in keys if k in body)

    calls = [(about(r), r["model"]) for r in marking]
    haiku, sonnet, opus = (AI.models[m].id for m in ("haiku", "sonnet", "opus"))
    assert ("Which theorem", haiku) in calls  # short answer: simple_marking
    assert [m for k, m in calls if k == "Why must volatility"] == [sonnet, opus]  # escalated
    assert ("Derive integration", sonnet) in calls  # proof_marking
    # Then one call explaining the wrong (rule-marked) true/false answer.
    assert calls[-1] == ("Volatility varies", sonnet) and len(calls) == 5
    assert "<student_answer>" in marking[0]["messages"][0]["content"][0]["text"]

    result = (await client.get(f"/api/v1/attempts/{attempt}")).json()
    assert result["status"] == "marked"
    marked = {i["type"]: i for i in result["items"]}
    assert marked["short_answer"]["score"] == 1.0 and marked["short_answer"]["marked_by"] == "ai"
    assert marked["explanation"]["score"] == 1.0
    assert marked["derivation"]["score"] == pytest.approx(1 / 3)
    assert marked["derivation"]["feedback"]["explanation"]["why_wrong"] == "No integration step."
    assert marked["derivation"]["mistake_category"] == "incomplete_justification"
    assert marked["true_false"]["feedback"]["explanation"]["why_wrong"] == "why 1"
    assert marked["true_false"]["mistake_category"] == "concept_confusion"
    assert marked["true_false"]["correct_answer"] == "False"
    assert marked["derivation"]["solution_md"] == "Worked solution."
    summary = result["summary"]
    assert (summary["correct"], summary["partial"], summary["incorrect"]) == (5, 1, 1)
    assert summary["score"] == pytest.approx((5 + 1 / 3) / 7)
    assert summary["next_steps"][0] == "Retry the 2 questions you got wrong."
    assert summary["time_taken_seconds"] is not None

    # Disputes go to the stronger model; exact marks can only be overridden.
    scripted.marks = [("Derive integration", mark([1, 1, 1]))]
    derivation = marked["derivation"]["question_attempt_id"]
    disputed = (await client.post(f"/api/v1/answers/{derivation}/dispute")).json()
    assert fake_claude.requests[-1]["model"] == AI.models["opus"].id
    assert {i["type"]: i["score"] for i in disputed["items"]}["derivation"] == 1.0
    exact_one = marked["true_false"]["question_attempt_id"]
    assert (await client.post(f"/api/v1/answers/{exact_one}/dispute")).status_code == 409
    overridden = (
        await client.post(f"/api/v1/answers/{exact_one}/override", json={"score": 1})
    ).json()
    assert {i["type"]: i["marked_by"] for i in overridden["items"]}["true_false"] == "override"
    assert overridden["summary"]["score"] == pytest.approx(1.0)

    # The bank remembers.
    wrong = await _get(client, f"/api/v1/questions?module_id={course['module']}&result=wrong")
    assert wrong == []
    history = await _get(client, f"/api/v1/attempts?module_id={course['module']}")
    assert history[0]["status"] == "marked" and history[0]["questions"] == 7


async def test_without_claude_answers_wait_for_you_to_mark(
    client: httpx.AsyncClient,
    course: dict[str, str],
    scripted: ScriptedClaude,
    fake_claude: FakeAnthropic,
    queue: RecordingQueue,
    deps: Deps,
) -> None:
    ids = await _bank(client, course, scripted, queue, deps)
    attempt = await _start(client, course, [ids["derivation"], ids["multiple_choice"]])
    await client.put(
        f"/api/v1/attempts/{attempt}/responses/{ids['derivation']}",
        json={"response": {"text": "x"}},
    )
    await client.post(f"/api/v1/attempts/{attempt}/submit")
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    fake_claude.error = anthropic.APIConnectionError(request=request)  # type: ignore[arg-type]
    await run_jobs(queue, deps)

    result = (await client.get(f"/api/v1/attempts/{attempt}")).json()
    derivation = next(i for i in result["items"] if i["type"] == "derivation")
    assert derivation["score"] is None and "Not marked" in derivation["feedback"]["unmarked"]
    assert result["summary"]["unmarked"] == 1
    assert "Mark the 1 unmarked answer yourself." in result["summary"]["next_steps"]
    overridden = await client.post(
        f"/api/v1/answers/{derivation['question_attempt_id']}/override", json={"score": 0.5}
    )
    assert overridden.json()["summary"]["unmarked"] == 0


async def test_filtered_quizzes_and_retired_questions(
    client: httpx.AsyncClient,
    course: dict[str, str],
    scripted: ScriptedClaude,
    queue: RecordingQueue,
    deps: Deps,
) -> None:
    ids = await _bank(client, course, scripted, queue, deps)
    built = await client.post(
        "/api/v1/quizzes",
        json={
            "module_id": course["module"],
            "types": ["multiple_choice", "true_false"],
            "count": 5,
        },
    )
    assert built.status_code == 201
    attempt = await _get(client, f"/api/v1/attempts/{built.json()['attempt_id']}")
    assert {i["type"] for i in attempt["items"]} == {"multiple_choice", "true_false"}

    unattempted = await _get(
        client, f"/api/v1/questions?module_id={course['module']}&result=unattempted"
    )
    assert len(unattempted) == 7  # starting a quiz is not attempting it
    retired = await client.patch(
        f"/api/v1/questions/{ids['numerical']}", json={"status": "retired"}
    )
    assert retired.json()["status"] == "retired"
    active = await _get(client, f"/api/v1/questions?module_id={course['module']}")
    assert ids["numerical"] not in {q["id"] for q in active}
    empty = await client.post(
        "/api/v1/quizzes", json={"module_id": course["module"], "difficulties": ["exam"]}
    )
    assert empty.status_code == 422 and empty.json()["error"]["code"] == "no_questions"


# --- exam mode -----------------------------------------------------------------------------------


async def test_a_mock_exam_turns_ai_off_and_closes_at_its_deadline(
    client: httpx.AsyncClient,
    course: dict[str, str],
    scripted: ScriptedClaude,
    queue: RecordingQueue,
    deps: Deps,
    db: AsyncSession,
) -> None:
    ids = await _bank(client, course, scripted, queue, deps)
    attempt = await _start(
        client,
        course,
        [ids["multiple_choice"], ids["numerical"]],
        kind="mock",
        time_limit_minutes=30,
    )
    exam = await _get(client, f"/api/v1/attempts/{attempt}")
    assert exam["mode"] == "exam" and exam["deadline"] is not None
    assert exam["quiz"]["time_limit_minutes"] == 30

    conversation = (await client.post("/api/v1/conversations", json={})).json()["id"]
    chat = await client.post(
        f"/api/v1/conversations/{conversation}/messages", json={"content": "help"}
    )
    assert chat.status_code == 423 and chat.json()["error"]["code"] == "exam_in_progress"
    generate = await client.post(
        "/api/v1/drafts", json={"module_id": course["module"], "kind": "questions"}
    )
    assert generate.status_code == 423
    other = await client.post(
        "/api/v1/quizzes",
        json={"module_id": course["module"], "question_ids": [ids["multiple_choice"]]},
    )
    assert other.status_code == 423

    # Time runs out: late answers are refused and the exam is submitted.
    await db.execute(
        update(QuizAttempt)
        .where(QuizAttempt.id == uuid.UUID(attempt))
        .values(deadline=datetime.now(UTC) - timedelta(minutes=5))
    )
    await db.commit()
    late = await client.put(
        f"/api/v1/attempts/{attempt}/responses/{ids['numerical']}",
        json={"response": {"value": "0.1172"}},
    )
    assert late.status_code == 409 and late.json()["error"]["code"] == "time_up"
    closed = await _get(client, f"/api/v1/attempts/{attempt}")
    assert closed["status"] != "in_progress" and closed["submitted_at"] is not None
    chat = await client.post(
        f"/api/v1/conversations/{conversation}/messages", json={"content": "help"}
    )
    assert chat.status_code == 200


async def test_the_open_mock_exam_is_found_for_the_timer(
    client: httpx.AsyncClient,
    course: dict[str, str],
    scripted: ScriptedClaude,
    queue: RecordingQueue,
    deps: Deps,
    db: AsyncSession,
) -> None:
    """Every page shows the timer of an open mock exam (GET /attempts/active-exam)."""
    assert (await client.get("/api/v1/attempts/active-exam")).json() is None
    ids = await _bank(client, course, scripted, queue, deps)
    practice = await _start(client, course, [ids["multiple_choice"]])
    assert (await client.get("/api/v1/attempts/active-exam")).json() is None  # not an exam
    await client.post(f"/api/v1/attempts/{practice}/submit")

    attempt = await _start(
        client, course, [ids["multiple_choice"]], kind="mock", time_limit_minutes=30
    )
    active = await _get(client, "/api/v1/attempts/active-exam")
    exam = await _get(client, f"/api/v1/attempts/{attempt}")
    assert active["attempt_id"] == attempt and active["deadline"] == exam["deadline"]
    assert active["title"] == exam["quiz"]["title"]

    # Stopping it early is submitting it: then there is no open exam.
    assert (await client.post(f"/api/v1/attempts/{attempt}/submit")).status_code == 200
    assert (await client.get("/api/v1/attempts/active-exam")).json() is None

    # One past its deadline is submitted when the timer asks, and is gone.
    late = await _start(
        client, course, [ids["multiple_choice"]], kind="mock", time_limit_minutes=30
    )
    await db.execute(
        update(QuizAttempt)
        .where(QuizAttempt.id == uuid.UUID(late))
        .values(deadline=datetime.now(UTC) - timedelta(minutes=5))
    )
    await db.commit()
    assert (await client.get("/api/v1/attempts/active-exam")).json() is None
    assert (await _get(client, f"/api/v1/attempts/{late}"))["submitted_at"] is not None


# --- photos of working --------------------------------------------------------------------------


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(buffer, "PNG")
    return buffer.getvalue()


async def test_a_photo_of_working_is_transcribed_for_you_to_check(
    client: httpx.AsyncClient,
    course: dict[str, str],
    scripted: ScriptedClaude,
    fake_claude: FakeAnthropic,
    queue: RecordingQueue,
    deps: Deps,
    db: AsyncSession,
) -> None:
    ids = await _bank(client, course, scripted, queue, deps)
    attempt = await _start(client, course, [ids["derivation"], ids["multiple_choice"]])
    photo = await client.post(
        f"/api/v1/attempts/{attempt}/responses/{ids['derivation']}/photo",
        params={"filename": "working.png"},
        content=_png(),
    )
    assert photo.status_code == 200, photo.text
    assert photo.json() == {"markdown": "$$f'(x) = 2x$$", "confidence": "high", "notes": ""}
    assert fake_claude.requests[-1]["messages"][0]["content"][0]["type"] == "image"
    item = next(
        i
        for i in (await _get(client, f"/api/v1/attempts/{attempt}"))["items"]
        if i["type"] == "derivation"
    )
    assert item["has_photo"] is True
    interactions = (await db.scalars(select(AIInteraction.feature))).all()
    assert "maths_transcription" in interactions

    choice = await client.post(
        f"/api/v1/attempts/{attempt}/responses/{ids['multiple_choice']}/photo",
        params={"filename": "x.png"},
        content=_png(),
    )
    assert choice.status_code == 422
    fake = await client.post(
        f"/api/v1/attempts/{attempt}/responses/{ids['derivation']}/photo",
        params={"filename": "x.png"},
        content=b"%PDF-1.7 not an image",
    )
    assert fake.status_code == 422


# --- the assistant can start drafts -----------------------------------------------------------


async def test_the_assistant_starts_a_draft_you_then_review(
    client: httpx.AsyncClient,
    course: dict[str, str],
    fake_claude: FakeAnthropic,
    queue: RecordingQueue,
) -> None:
    from tests.fakes import reply, tool_use

    fake_claude.stream_script = [
        reply(
            tool_use("start_draft", {"kind": "flashcards", "module_code": "math260", "count": 5})
        ),
        reply(text("I've started a flashcard draft.")),
    ]
    conversation = (await client.post("/api/v1/conversations", json={})).json()["id"]
    response = await client.post(
        f"/api/v1/conversations/{conversation}/messages", json={"content": "Make me flashcards"}
    )
    assert "event: link" in response.text
    assert queue.jobs and queue.jobs[0][0] == "generate_draft"
    detail = await _get(client, f"/api/v1/conversations/{conversation}")
    [link] = detail["messages"][-1]["links"]
    assert link["kind"] == "draft" and link["label"] == "MATH260 flashcards"
    draft = await _get(client, f"/api/v1/drafts/{link['id']}")
    assert draft["kind"] == "flashcards" and draft["request"]["count"] == 5
