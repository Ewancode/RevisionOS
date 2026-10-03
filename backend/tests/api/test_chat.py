"""The assistant end to end, with a scripted Claude: retrieval, the agent
loop, citation checking, provenance, budgets, pending actions and usage."""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import ClaudeClient
from app.core.config import get_config
from app.ingestion.pipeline import Deps
from app.models import AIInteraction, AIUsage, Message, PendingAction, User
from tests import factories
from tests.fakes import FakeAnthropic, RecordingQueue, cite, reply, text, tool_use
from tests.support import create_module, ingest, make_user, signed_in

pytestmark = pytest.mark.db

CHAT = get_config().ai.chat
LECTURE = [
    "Black-Scholes assumptions: the underlying follows geometric Brownian motion, "
    "volatility and the risk-free rate are constant, and there are no dividends.",
    "Integration by parts follows from the product rule for derivatives.",
    "The Central Limit Theorem says sample means are approximately normal.",
]


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
    """MATH260 with one three-page lecture, indexed."""
    module = await create_module(client)
    doc = await ingest(
        client, deps, queue, module["id"], factories.pdf(tmp_path / "l.pdf", LECTURE), "Week 3.pdf"
    )
    return {"module": module["id"], "document": doc}


async def _conversation(client: httpx.AsyncClient, **body: str) -> str:
    response = await client.post("/api/v1/conversations", json=body)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _ask(
    client: httpx.AsyncClient, conversation: str, question: str
) -> list[tuple[str, Any]]:
    """Send a message and parse the server-sent events."""
    response = await client.post(
        f"/api/v1/conversations/{conversation}/messages", json={"content": question}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    events = []
    for frame in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in frame.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def _sent_sources(request: dict[str, Any]) -> list[dict[str, Any]]:
    """Every search_result block in a request, in the order Claude sees them."""
    found = []
    for message in request["messages"]:
        content = message["content"]
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):  # echoed assistant blocks
                continue
            if block.get("type") == "search_result":
                found.append(block)
            elif block.get("type") == "tool_result" and isinstance(block["content"], list):
                found.extend(b for b in block["content"] if b.get("type") == "search_result")
    return found


def _cite_first_page_with(phrase: str) -> Any:
    def respond(request: dict[str, Any]) -> dict[str, Any]:
        sources = _sent_sources(request)
        index = next(i for i, s in enumerate(sources) if phrase in s["content"][0]["text"])
        return reply(
            text(
                "The model assumes constant volatility and no dividends.",
                cite(index, sources[index]["source"], "assumptions"),
            ),
            text("\n\nIt also assumes geometric Brownian motion."),
        )

    return respond


# --- answers and citations ---------------------------------------------------------------


async def test_answer_cites_the_page_it_came_from(
    client: httpx.AsyncClient,
    course: dict[str, str],
    fake_claude: FakeAnthropic,
    db: AsyncSession,
) -> None:
    fake_claude.stream_script = [_cite_first_page_with("Black-Scholes")]
    conversation = await _conversation(client, module_id=course["module"])

    events = await _ask(client, conversation, "What does Black-Scholes assume?")

    kinds = [kind for kind, _ in events]
    assert kinds[0] == "status" and kinds[-1] == "done"
    assert "".join(e["text"] for k, e in events if k == "delta").startswith("The model assumes")
    done = events[-1][1]
    assert done["status"] == "complete"
    assert done["content"].startswith(
        "The model assumes constant volatility and no dividends. [[1]](#cite-1)"
    )
    [citation] = done["citations"]
    assert citation | {"quote": ""} == {
        "n": 1,
        "document_id": course["document"],
        "filename": "Week 3.pdf",
        "page_no": 1,
        "source_tier": "university",
        "module_code": "MATH260",
        "heading_path": citation["heading_path"],
        "quote": "",
    }
    assert done["provenance"] == ["university"]

    # The request: routed model and effort, cached prefix, tools, fallback,
    # and the passages sent as citable search results before the question.
    [request] = fake_claude.requests
    assert request["model"] == get_config().ai.models["sonnet"].id
    assert request["output_config"] == {"effort": "medium"}
    assert request["cache_control"] == {"type": "ephemeral"}
    [system] = request["system"]
    assert system["cache_control"] == {"type": "ephemeral"}
    assert request["beta"] and request["fallbacks"] == "default"
    assert "tool_choice" not in request
    assert {t["name"] for t in request["tools"]} == {
        "search_materials",
        "read_page",
        "list_materials",
        "start_draft",
        "request_delete_document",
        "request_delete_topic",
        "request_delete_module",
    }
    content = request["messages"][-1]["content"]
    assert all(b["citations"] == {"enabled": True} for b in content[:-1])
    assert "asking from the module MATH260" in content[-1]["text"]
    assert content[-1]["text"].endswith("What does Black-Scholes assume?")

    # Saved, titled from the question, and the usage recorded.
    detail = (await client.get(f"/api/v1/conversations/{conversation}")).json()
    assert detail["title"] == "What does Black-Scholes assume?"
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["citations"] == done["citations"]
    [usage] = (await db.scalars(select(AIUsage))).all()
    assert usage.feature == "chat" and str(usage.module_id) == course["module"]


async def test_citations_not_backed_by_a_sent_passage_are_dropped(
    client: httpx.AsyncClient, course: dict[str, str], fake_claude: FakeAnthropic
) -> None:
    def fabricate(request: dict[str, Any]) -> dict[str, Any]:
        real = _sent_sources(request)[0]["source"]
        return reply(
            text("Out of range.", cite(99, real)),
            text(" Wrong source.", cite(0, f"doc:{uuid.uuid4()}#page=1")),
            text(
                " Wrong kind.",
                SimpleNamespace(type="char_location", search_result_index=0, source=real),
            ),
        )

    fake_claude.stream_script = [fabricate]
    events = await _ask(client, await _conversation(client), "Black-Scholes assumptions?")

    done = events[-1][1]
    assert done["citations"] == []
    assert "#cite-" not in done["content"]
    # No verified citation means the answer is badged general knowledge.
    assert done["provenance"] == ["general"]


async def test_claude_searches_again_and_cites_what_the_tool_returned(
    client: httpx.AsyncClient,
    course: dict[str, str],
    fake_claude: FakeAnthropic,
    db: AsyncSession,
) -> None:
    def cite_last(request: dict[str, Any]) -> dict[str, Any]:
        sources = _sent_sources(request)
        index = next(
            i
            for i, s in reversed(list(enumerate(sources)))
            if "Central Limit" in s["content"][0]["text"]
        )
        return reply(
            text("Sample means are approximately normal.", cite(index, sources[index]["source"]))
        )

    fake_claude.stream_script = [
        reply(
            tool_use(
                "search_materials", {"query": "central limit theorem", "module_code": "math260"}
            )
        ),
        cite_last,
    ]
    events = await _ask(client, await _conversation(client), "what about the second one?")

    statuses = [e["text"] for k, e in events if k == "status"]
    assert statuses == [
        "Searching your materials",
        "Searching math260 materials for “central limit theorem”",
    ]
    _, second = fake_claude.requests
    assert second["messages"][-2]["role"] == "assistant"
    [result] = second["messages"][-1]["content"]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_1"
    assert not result["is_error"]
    done = events[-1][1]
    assert done["citations"][0]["page_no"] == 3
    assert done["steps"] == statuses
    interactions = (
        await db.scalars(select(AIInteraction).order_by(AIInteraction.created_at))
    ).all()
    assert interactions[0].tool_calls == [
        {
            "name": "search_materials",
            "input": {"query": "central limit theorem", "module_code": "math260"},
        }
    ]
    assert interactions[1].tool_calls is None
    # Stored as SQL NULL, not a JSON null.
    no_tools = await db.scalar(
        select(func.count()).select_from(AIInteraction).where(AIInteraction.tool_calls.is_(None))
    )
    assert no_tools == 1


async def test_read_page_returns_the_whole_page_as_a_citable_passage(
    client: httpx.AsyncClient, course: dict[str, str], fake_claude: FakeAnthropic
) -> None:
    fake_claude.stream_script = [
        reply(tool_use("read_page", {"document_id": course["document"], "page_no": 2})),
        lambda request: reply(
            text(
                "By the product rule.",
                cite(len(_sent_sources(request)) - 1, f"doc:{course['document']}#page=2"),
            )
        ),
    ]
    events = await _ask(client, await _conversation(client), "Show me page 2")
    [result] = fake_claude.requests[1]["messages"][-1]["content"]
    [block] = result["content"]
    assert block["title"] == "Week 3.pdf — page 2"
    assert "product rule" in block["content"][0]["text"]
    assert events[-1][1]["citations"][0]["page_no"] == 2


async def test_bad_tool_input_is_reported_to_claude_not_run(
    client: httpx.AsyncClient, course: dict[str, str], fake_claude: FakeAnthropic
) -> None:
    fake_claude.stream_script = [
        reply(
            tool_use("read_page", {"document_id": "not-a-uuid", "page_no": 0}),
            tool_use("drop_tables", {}, "toolu_2"),
        ),
        reply(text("Sorry.")),
    ]
    await _ask(client, await _conversation(client), "page?")
    results = fake_claude.requests[1]["messages"][-1]["content"]
    assert [r["is_error"] for r in results] == [True, True]
    assert "no tool called drop_tables" in results[1]["content"]


async def test_the_loop_stops_after_the_configured_number_of_calls(
    client: httpx.AsyncClient, course: dict[str, str], fake_claude: FakeAnthropic
) -> None:
    fake_claude.stream_script = [
        reply(tool_use("list_materials", {})) for _ in range(CHAT.max_model_calls + 2)
    ]
    events = await _ask(client, await _conversation(client), "Loop forever")
    assert len(fake_claude.requests) == CHAT.max_model_calls
    assert "tool_choice" not in fake_claude.requests[-2]
    # The last call must answer with what it has.
    assert fake_claude.requests[-1]["tool_choice"] == {"type": "none"}
    assert events[-1][0] == "done"


async def test_no_material_is_said_plainly(
    client: httpx.AsyncClient, fake_claude: FakeAnthropic
) -> None:
    events = await _ask(client, await _conversation(client), "Explain quaternions")
    [request] = fake_claude.requests
    content = request["messages"][-1]["content"]
    assert [b["type"] for b in content] == ["text"]
    assert content[0]["text"].startswith("No passages in the student's materials matched")
    assert events[-1][1]["provenance"] == ["general"]


async def test_follow_ups_resend_earlier_turns_as_plain_text(
    client: httpx.AsyncClient, course: dict[str, str], fake_claude: FakeAnthropic
) -> None:
    fake_claude.stream_script = [_cite_first_page_with("Black-Scholes"), reply(text("Yes."))]
    conversation = await _conversation(client)
    await _ask(client, conversation, "What does Black-Scholes assume?")
    await _ask(client, conversation, "Is volatility constant?")

    history = fake_claude.requests[1]["messages"]
    assert history[0] == {"role": "user", "content": "What does Black-Scholes assume?"}
    assert history[1]["role"] == "assistant"
    assert history[1]["content"].startswith(
        "The model assumes constant volatility and no dividends."
    )
    assert "#cite-" not in history[1]["content"]
    assert history[2]["role"] == "user"


# --- failures ---------------------------------------------------------------------------


async def test_refused_answers_are_discarded(
    client: httpx.AsyncClient,
    course: dict[str, str],
    fake_claude: FakeAnthropic,
    db: AsyncSession,
) -> None:
    fake_claude.stream_script = [reply(text("Partial"), stop_reason="refusal")]
    events = await _ask(client, await _conversation(client), "something")
    kind, error = events[-1]
    assert kind == "error" and error["code"] == "ai_refused"
    assert error["saved"]["status"] == "error" and error["saved"]["content"] == "Partial"
    [usage] = (await db.scalars(select(AIUsage))).all()  # refused calls are billed
    assert usage.feature == "chat"


async def test_truncated_answers_say_so(
    client: httpx.AsyncClient, course: dict[str, str], fake_claude: FakeAnthropic
) -> None:
    fake_claude.stream_script = [reply(text("A long answer"), stop_reason="max_tokens")]
    events = await _ask(client, await _conversation(client), "Tell me everything")
    assert events[-1][1]["content"].endswith("*(This answer was cut off at the length limit.)*")


async def test_budget_reached_stops_before_calling_claude(
    client: httpx.AsyncClient, owner: User, fake_claude: FakeAnthropic, db: AsyncSession
) -> None:
    db.add(
        AIInteraction(
            id=uuid.uuid4(),
            user_id=owner.id,
            feature="chat",
            requested_model="m",
            prompt_version="v",
            status="ok",
        )
    )
    await db.flush()
    interaction = (await db.scalars(select(AIInteraction))).one()
    db.add(
        AIUsage(
            user_id=owner.id,
            interaction_id=interaction.id,
            feature="chat",
            model="m",
            input_tokens=1,
            output_tokens=1,
            estimated_cost_usd=1000.0,
        )
    )
    await db.commit()

    events = await _ask(client, await _conversation(client), "hello")
    kind, error = events[-1]
    assert kind == "error" and error["code"] == "ai_budget_reached"
    assert fake_claude.requests == []
    statuses = (await db.scalars(select(AIInteraction.status))).all()
    assert "budget_blocked" in statuses


async def test_without_an_api_key_the_assistant_explains(
    db_app: FastAPI, client: httpx.AsyncClient
) -> None:
    db_app.state.claude = ClaudeClient(None, get_config().ai)
    conversation = await _conversation(client)
    response = await client.post(
        f"/api/v1/conversations/{conversation}/messages", json={"content": "hi"}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_not_configured"


async def test_one_answer_at_a_time_per_conversation(
    db_app: FastAPI, client: httpx.AsyncClient
) -> None:
    conversation = await _conversation(client)
    await db_app.state.redis.set(f"chat-answer:{conversation}", "1")
    response = await client.post(
        f"/api/v1/conversations/{conversation}/messages", json={"content": "hi"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "answer_in_progress"


async def test_the_lock_is_released_after_an_answer(
    db_app: FastAPI, client: httpx.AsyncClient
) -> None:
    conversation = await _conversation(client)
    await _ask(client, conversation, "one")
    assert await db_app.state.redis.get(f"chat-answer:{conversation}") is None


async def test_messages_are_length_limited(client: httpx.AsyncClient) -> None:
    conversation = await _conversation(client)
    response = await client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"content": "x" * (CHAT.max_message_chars + 1)},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "message_too_long"


# --- conversations ------------------------------------------------------------------------


async def test_conversations_list_newest_first_and_delete(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    first = await _conversation(client)
    second = await _conversation(client)
    await _ask(client, first, "bump")
    listed = [c["id"] for c in (await client.get("/api/v1/conversations")).json()]
    assert listed == [first, second]

    assert (await client.delete(f"/api/v1/conversations/{first}")).status_code == 204
    assert (await client.get(f"/api/v1/conversations/{first}")).status_code == 404
    assert (await db.scalars(select(Message))).all() == []


async def test_a_topic_conversation_takes_its_module(
    client: httpx.AsyncClient, course: dict[str, str]
) -> None:
    topic = (
        await client.post(f"/api/v1/modules/{course['module']}/topics", json={"title": "Options"})
    ).json()
    response = await client.post("/api/v1/conversations", json={"topic_id": topic["id"]})
    assert response.json()["module_id"] == course["module"]
    other = await create_module(client, "MATH111")
    mismatch = await client.post(
        "/api/v1/conversations", json={"topic_id": topic["id"], "module_id": other["id"]}
    )
    assert mismatch.status_code == 422


# --- pending actions -------------------------------------------------------------------


async def _request_delete(
    client: httpx.AsyncClient, course: dict[str, str], fake_claude: FakeAnthropic
) -> dict[str, Any]:
    fake_claude.stream_script = [
        reply(tool_use("request_delete_document", {"document_id": course["document"]})),
        reply(text("I've asked you to confirm deleting Week 3.pdf.")),
    ]
    events = await _ask(client, await _conversation(client), "Delete my week 3 lecture")
    [action] = [e for k, e in events if k == "action"]
    assert action["status"] == "pending"
    assert action["preview"].startswith("Delete “Week 3.pdf”? It moves to the trash")
    done = events[-1][1]
    assert [a["id"] for a in done["actions"]] == [action["id"]]
    return dict(action)


async def test_claude_can_only_request_a_delete(
    client: httpx.AsyncClient, course: dict[str, str], fake_claude: FakeAnthropic
) -> None:
    await _request_delete(client, course, fake_claude)
    result = fake_claude.requests[1]["messages"][-1]["content"][0]
    assert "nothing has been deleted" in result["content"]
    # Still there until you confirm.
    assert (await client.get(f"/api/v1/documents/{course['document']}")).status_code == 200


async def test_confirming_deletes_to_the_trash_once(
    client: httpx.AsyncClient, course: dict[str, str], fake_claude: FakeAnthropic
) -> None:
    action = await _request_delete(client, course, fake_claude)
    response = await client.post(f"/api/v1/pending-actions/{action['id']}/confirm")
    assert response.status_code == 200 and response.json()["status"] == "confirmed"
    assert (await client.get(f"/api/v1/documents/{course['document']}")).status_code == 404
    trash = (await client.get("/api/v1/trash")).json()
    assert [d["id"] for d in trash["documents"]] == [course["document"]]

    again = await client.post(f"/api/v1/pending-actions/{action['id']}/confirm")
    assert again.status_code == 409


async def test_cancelled_and_expired_requests_cannot_be_confirmed(
    client: httpx.AsyncClient,
    course: dict[str, str],
    fake_claude: FakeAnthropic,
    db: AsyncSession,
) -> None:
    action = await _request_delete(client, course, fake_claude)
    assert (await client.post(f"/api/v1/pending-actions/{action['id']}/cancel")).json()[
        "status"
    ] == "cancelled"
    assert (await client.post(f"/api/v1/pending-actions/{action['id']}/confirm")).status_code == 409

    second = await _request_delete(client, course, fake_claude)
    await db.execute(
        update(PendingAction)
        .where(PendingAction.id == uuid.UUID(second["id"]))
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db.commit()
    expired = await client.post(f"/api/v1/pending-actions/{second['id']}/confirm")
    assert expired.status_code == 409
    assert "expired" in expired.json()["error"]["message"]
    assert (await client.get(f"/api/v1/documents/{course['document']}")).status_code == 200


async def test_confirming_needs_the_csrf_token(
    client: httpx.AsyncClient, course: dict[str, str], fake_claude: FakeAnthropic
) -> None:
    action = await _request_delete(client, course, fake_claude)
    response = await client.post(
        f"/api/v1/pending-actions/{action['id']}/confirm", headers={"X-CSRF-Token": "forged"}
    )
    assert response.status_code == 403


async def test_requests_for_missing_targets_are_errors_for_claude(
    client: httpx.AsyncClient,
    course: dict[str, str],
    fake_claude: FakeAnthropic,
    db: AsyncSession,
) -> None:
    fake_claude.stream_script = [
        reply(tool_use("request_delete_module", {"module_id": str(uuid.uuid4())})),
        reply(text("That module doesn't exist.")),
    ]
    events = await _ask(client, await _conversation(client), "Delete module X")
    assert [k for k, _ in events if k == "action"] == []
    [result] = fake_claude.requests[1]["messages"][-1]["content"]
    assert result["is_error"]
    assert (await db.scalars(select(PendingAction))).all() == []


# --- usage dashboard ------------------------------------------------------------------------


async def test_usage_dashboard_breaks_down_cost(
    client: httpx.AsyncClient, course: dict[str, str], fake_claude: FakeAnthropic
) -> None:
    fake_claude.stream_script = [reply(text("Hi"), input_tokens=10_000, output_tokens=1_000)]
    await _ask(client, await _conversation(client, module_id=course["module"]), "hi")

    usage = (await client.get("/api/v1/ai/usage")).json()
    ai = get_config().ai
    sonnet = ai.models["sonnet"].pricing
    expected = round(
        (10_000 * sonnet.input + 1_000 * sonnet.output) / 1e6 * ai.budget.usd_to_currency, 4
    )
    assert usage["currency"] == "GBP"
    assert usage["totals"]["requests"] == 1 and usage["totals"]["cost"] == expected
    assert usage["by_feature"] == [
        {"key": "chat", "label": "Assistant", "requests": 1, "tokens": 11_000, "cost": expected}
    ]
    assert usage["by_model"][0]["label"] == "Sonnet"
    assert usage["by_module"][0]["label"] == "MATH260"
    assert len(usage["by_day"]) == ai.usage_dashboard.default_days
    assert usage["by_day"][-1]["requests"] == 1

    too_long = await client.get(
        "/api/v1/ai/usage", params={"days": ai.usage_dashboard.max_days + 1}
    )
    assert too_long.status_code == 422
