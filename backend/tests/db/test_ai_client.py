"""The Claude gateway: routing, effort, budget enforcement and cost records."""

import io
import uuid
from datetime import UTC, datetime, timedelta

import anthropic
import httpx
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import budget as budget_module
from app.ai.budget import BudgetGuard
from app.ai.client import ClaudeClient
from app.ai.transcription import PROMPT_VERSION, Transcription, prepare_image, transcribe_page
from app.core.config import get_config
from app.core.errors import AppError
from app.models import AIInteraction, AIUsage, User
from tests.fakes import FakeAnthropic, transcription
from tests.support import make_user

pytestmark = pytest.mark.db

AI = get_config().ai
SONNET = AI.models["sonnet"]


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (3000, 2000), "white").save(buffer, "PNG")
    return buffer.getvalue()


async def _transcribe(client: ClaudeClient, db: AsyncSession, user: User) -> Transcription:
    return await transcribe_page(
        client,
        db,
        user_id=user.id,
        document_id=None,
        module_id=None,
        image=prepare_image(_png(), 1568),
        page_no=2,
        filename="Week 4.pdf",
        text_hint="1 × 2 2 3 4",
    )


async def _usage(db: AsyncSession) -> list[AIUsage]:
    return list((await db.scalars(select(AIUsage))).all())


async def test_request_uses_the_configured_route(
    db: AsyncSession, claude: ClaudeClient, fake_claude: FakeAnthropic
) -> None:
    user = await make_user(db)
    result = await _transcribe(claude, db, user)

    [request] = fake_claude.requests
    assert request["model"] == SONNET.id
    assert request["output_config"]["effort"] == "high"
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert request["max_tokens"] == 8000
    # Sonnet is configured for the server-side refusal fallback.
    assert request["beta"] is True
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    assert request["fallbacks"] == "default"
    # The image was downscaled before sending, and the text layer is labelled.
    image, text = request["messages"][0]["content"]
    assert image["type"] == "image"
    assert "<text_layer>" in text["text"]
    assert result.markdown == "$$x^2$$"
    assert result.confidence == "high"


async def test_usage_and_cost_are_recorded(db: AsyncSession, claude: ClaudeClient) -> None:
    user = await make_user(db)
    await _transcribe(claude, db, user)

    [usage] = await _usage(db)
    assert (usage.input_tokens, usage.output_tokens, usage.model) == (1500, 400, SONNET.id)
    expected = (1500 * SONNET.pricing.input + 400 * SONNET.pricing.output) / 1_000_000
    assert usage.estimated_cost_usd == pytest.approx(expected)
    [interaction] = (await db.scalars(select(AIInteraction))).all()
    assert interaction.status == "ok"
    assert interaction.prompt_version == PROMPT_VERSION


async def test_fallback_model_is_priced_conservatively(
    db: AsyncSession, claude: ClaudeClient, fake_claude: FakeAnthropic
) -> None:
    fake_claude.respond = lambda _: {**transcription("x"), "model": "claude-unknown-fallback"}
    user = await make_user(db)
    await _transcribe(claude, db, user)

    [usage] = await _usage(db)
    priciest = max(m.pricing.output for m in AI.models.values())
    assert usage.model == "claude-unknown-fallback"
    assert usage.estimated_cost_usd >= 400 * priciest / 1_000_000


async def test_refusals_are_recorded_and_raised(
    db: AsyncSession, claude: ClaudeClient, fake_claude: FakeAnthropic
) -> None:
    fake_claude.respond = lambda _: {"text": "", "stop_reason": "refusal"}
    user = await make_user(db)
    with pytest.raises(AppError) as exc_info:
        await _transcribe(claude, db, user)
    assert exc_info.value.code == "ai_refused"
    assert len(await _usage(db)) == 1  # refused calls can still be billed


async def test_api_errors_become_a_clear_failure(
    db: AsyncSession, claude: ClaudeClient, fake_claude: FakeAnthropic
) -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    fake_claude.error = anthropic.APIConnectionError(request=request)  # type: ignore[arg-type]
    user = await make_user(db)
    with pytest.raises(AppError) as exc_info:
        await _transcribe(claude, db, user)
    assert exc_info.value.code == "ai_unavailable"
    [interaction] = (await db.scalars(select(AIInteraction))).all()
    assert (interaction.status, interaction.error_code) == ("error", "APIConnectionError")


async def test_no_api_key_means_no_call(db: AsyncSession) -> None:
    user = await make_user(db)
    with pytest.raises(AppError) as exc_info:
        await _transcribe(ClaudeClient(None, AI), db, user)
    assert exc_info.value.code == "ai_not_configured"


# --- budget --------------------------------------------------------------------


async def _spend(db: AsyncSession, user: User, usd: float, when: datetime) -> None:
    interaction = AIInteraction(
        id=uuid.uuid4(),
        user_id=user.id,
        feature="test",
        requested_model="m",
        prompt_version="v",
        status="ok",
    )
    db.add(interaction)
    db.add(
        AIUsage(
            user_id=user.id,
            interaction_id=interaction.id,
            feature="test",
            model="m",
            input_tokens=0,
            output_tokens=0,
            estimated_cost_usd=usd,
            created_at=when,
        )
    )
    await db.commit()


async def test_budget_blocks_before_calling_claude(
    db: AsyncSession, claude: ClaudeClient, fake_claude: FakeAnthropic
) -> None:
    user = await make_user(db)
    cap_usd = AI.budget.daily_cap / AI.budget.usd_to_currency
    await _spend(db, user, cap_usd - 0.0001, datetime.now(UTC))

    with pytest.raises(AppError) as exc_info:
        await _transcribe(claude, db, user)

    assert exc_info.value.code == "ai_budget_reached"
    assert exc_info.value.status_code == 429
    assert fake_claude.requests == []  # never sent
    statuses = (await db.scalars(select(AIInteraction.status))).all()
    assert "budget_blocked" in statuses


async def test_budget_status_converts_and_respects_uk_days(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await make_user(db)
    # 23:30 UTC on 30 June is 00:30 on 1 July in London (BST): a new day
    # and a new month there, though not yet in UTC.
    now = datetime(2026, 6, 30, 23, 30, tzinfo=UTC)
    monkeypatch.setattr(budget_module, "utcnow", lambda: now)
    await _spend(db, user, 1.00, now - timedelta(hours=1))  # 22:30 UTC = 23:30 London, 30 June
    await _spend(db, user, 0.50, now - timedelta(minutes=10))  # 00:20 London, 1 July

    status = await BudgetGuard(db, user.id, AI.budget).status()

    rate = AI.budget.usd_to_currency
    assert status.currency == "GBP"
    assert status.spent_today == pytest.approx(0.50 * rate)
    assert status.spent_this_month == pytest.approx(0.50 * rate)
    assert not status.exhausted
