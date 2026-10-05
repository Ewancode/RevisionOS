"""The assistant: conversations, streamed answers and pending actions
(ARCHITECTURE.md sections 8-9)."""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.ai.chat import (
    ActionRequested,
    ChatOrchestrator,
    Delta,
    Done,
    Failed,
    LinkAdded,
    Status,
)
from app.api.deps import Client, Config, CurrentUser, DbSession, rate_limited
from app.core.errors import AppError
from app.models import Message
from app.schemas.chat import (
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    MessageCreate,
    MessageOut,
    PendingActionOut,
)
from app.services.chat import ConversationService
from app.services.documents import DocumentService
from app.services.pending_actions import PendingActionService
from app.services.quizzes import ensure_no_exam
from app.services.structure import ModuleService, TopicService

router = APIRouter(tags=["chat"])


def _conversations(
    db: DbSession, user: CurrentUser, client: Client, config: Config
) -> ConversationService:
    return ConversationService(db, user.id, client, config=config)


Conversations = Annotated[ConversationService, Depends(_conversations)]


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(conversations: Conversations) -> list[ConversationOut]:
    return [ConversationOut.model_validate(c) for c in await conversations.list()]


@router.post("/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate, conversations: Conversations
) -> ConversationOut:
    return ConversationOut.model_validate(await conversations.create(body))


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID, conversations: Conversations
) -> ConversationDetail:
    return await conversations.detail(conversation_id)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: uuid.UUID, conversations: Conversations) -> None:
    await conversations.delete(conversation_id)


def _sse(event: str, payload: BaseModel | dict[str, object]) -> str:
    data = payload.model_dump_json() if isinstance(payload, BaseModel) else json.dumps(payload)
    return f"event: {event}\ndata: {data}\n\n"


@router.post(
    "/conversations/{conversation_id}/messages",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
    dependencies=[rate_limited("ai")],
)
async def send_message(
    conversation_id: uuid.UUID,
    body: MessageCreate,
    request: Request,
    db: DbSession,
    user: CurrentUser,
    client: Client,
    config: Config,
    conversations: Conversations,
) -> StreamingResponse:
    """Ask a question; the answer streams back as server-sent events:

    - `status` {text}: what the assistant is doing ("Searching …")
    - `delta` {text}: the next piece of answer text
    - `action` PendingAction: a deletion awaiting your confirmation
    - `done` Message: the saved answer, with verified citations
    - `error` {code, message, saved: Message}: the answer failed or was refused
    """
    conversation = await conversations.get(conversation_id)
    conversations.check_length(body.content)
    # No AI help during a mock exam: enforced here, not just in the UI.
    await ensure_no_exam(db, user.id, config, request.app.state.jobs)
    claude = request.app.state.claude
    if not claude.available:
        raise AppError(
            "ai_not_configured", "Claude is not configured: set ANTHROPIC_API_KEY in .env.", 503
        )
    redis = request.app.state.redis
    lock = f"chat-answer:{conversation.id}"
    if not await redis.set(lock, "1", nx=True, ex=config.ai.chat.answer_lock_seconds):
        raise AppError("answer_in_progress", "Wait for the current answer to finish.", 409)
    await conversations.name_from_first_message(conversation, body.content)
    orchestrator = ChatOrchestrator(
        db,
        user.id,
        client,
        claude=claude,
        embedder=request.app.state.embedder,
        config=config,
        jobs=request.app.state.jobs,
    )

    async def with_actions(message: Message) -> MessageOut:
        actions = await PendingActionService(db, user.id, client, config=config).list_for_messages(
            [message.id]
        )
        return MessageOut.model_validate(message).model_copy(
            update={"actions": [PendingActionOut.model_validate(a) for a in actions]}
        )

    async def events() -> AsyncIterator[str]:
        try:
            async for event in orchestrator.answer(conversation, body.content):
                if isinstance(event, Status):
                    yield _sse("status", {"text": event.text})
                elif isinstance(event, Delta):
                    yield _sse("delta", {"text": event.text})
                elif isinstance(event, LinkAdded):
                    yield _sse("link", event.link)
                elif isinstance(event, ActionRequested):
                    yield _sse("action", PendingActionOut.model_validate(event.action))
                elif isinstance(event, Done):
                    yield _sse("done", await with_actions(event.message))
                elif isinstance(event, Failed):
                    saved = await with_actions(event.saved)
                    yield _sse(
                        "error",
                        {
                            "code": event.code,
                            "message": event.message,
                            "saved": saved.model_dump(mode="json"),
                        },
                    )
        finally:
            await redis.delete(lock)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# --- pending actions ----------------------------------------------------------------


def _pending(
    db: DbSession, user: CurrentUser, client: Client, config: Config
) -> PendingActionService:
    return PendingActionService(db, user.id, client, config=config)


Pending = Annotated[PendingActionService, Depends(_pending)]


@router.post("/pending-actions/{action_id}/confirm", response_model=PendingActionOut)
async def confirm_pending_action(
    action_id: uuid.UUID,
    request: Request,
    pending: Pending,
    db: DbSession,
    user: CurrentUser,
    client: Client,
    config: Config,
) -> PendingActionOut:
    """Carry out a deletion Claude requested. Only reachable from your signed-in
    browser with a CSRF token; the item goes to the trash."""
    documents = DocumentService(
        db,
        user.id,
        client,
        storage=request.app.state.storage,
        jobs=request.app.state.jobs,
        config=config,
    )
    action = await pending.confirm(
        action_id, documents, ModuleService(db, user.id, client), TopicService(db, user.id, client)
    )
    return PendingActionOut.model_validate(action)


@router.post("/pending-actions/{action_id}/cancel", response_model=PendingActionOut)
async def cancel_pending_action(action_id: uuid.UUID, pending: Pending) -> PendingActionOut:
    return PendingActionOut.model_validate(await pending.cancel(action_id))
