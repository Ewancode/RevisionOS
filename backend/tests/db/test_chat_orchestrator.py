"""Stopping an answer part-way (the Stop button, or a dropped connection)."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chat import ChatOrchestrator, Delta
from app.ai.client import ClaudeClient
from app.core.config import get_config
from app.models import AIInteraction, AIUsage, Conversation, Message
from app.retrieval.embeddings import HashingProvider
from app.services.common import ClientInfo
from tests.fakes import FakeAnthropic, reply, text
from tests.support import make_user

pytestmark = pytest.mark.db


async def test_a_stopped_answer_keeps_what_was_shown_and_its_cost(
    db: AsyncSession, claude: ClaudeClient, fake_claude: FakeAnthropic
) -> None:
    user = await make_user(db)
    conversation = Conversation(id=uuid.uuid4(), user_id=user.id, title="t")
    db.add(conversation)
    await db.commit()
    fake_claude.stream_script = [reply(text("Integration by parts comes from the product rule."))]
    config = get_config()
    orchestrator = ChatOrchestrator(
        db,
        user.id,
        ClientInfo(None, None),
        claude=claude,
        embedder=HashingProvider(config.retrieval.embeddings.dimensions),
        config=config,
    )

    events = orchestrator.answer(conversation, "Where does integration by parts come from?")
    async for event in events:
        if isinstance(event, Delta):
            break  # the browser goes away after the first piece of text
    await events.aclose()

    answer = (await db.scalars(select(Message).where(Message.role == "assistant"))).one()
    assert answer.status == "stopped"
    assert answer.content == "Integration by parts com"  # the first half
    # The tokens streamed so far are billed, so they count against the budget.
    [usage] = (await db.scalars(select(AIUsage))).all()
    assert usage.feature == "chat" and usage.output_tokens > 0
    [interaction] = (await db.scalars(select(AIInteraction))).all()
    assert interaction.error_code == "cancelled"
