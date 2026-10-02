"""Conversations with the assistant: list, start, read, delete."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig
from app.core.errors import AppError
from app.models import Conversation, Message
from app.schemas.chat import (
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    MessageOut,
    PendingActionOut,
)
from app.services.common import ClientInfo, ScopedService, not_found
from app.services.pending_actions import PendingActionService

NEW_TITLE = "New conversation"
TITLE_CHARS = 80
LIST_LIMIT = 200


def title_from(text: str) -> str:
    first_line = text.strip().splitlines()[0].strip() if text.strip() else NEW_TITLE
    if len(first_line) <= TITLE_CHARS:
        return first_line
    return first_line[: TITLE_CHARS - 1].rstrip() + "…"


class ConversationService(ScopedService):
    def __init__(
        self, db: AsyncSession, user_id: uuid.UUID, client: ClientInfo, *, config: AppConfig
    ) -> None:
        super().__init__(db, user_id, client)
        self.config = config

    async def list(self) -> Sequence[Conversation]:
        rows = await self.db.scalars(
            select(Conversation)
            .where(Conversation.user_id == self.user_id)
            .order_by(Conversation.updated_at.desc())
            .limit(LIST_LIMIT)
        )
        return rows.all()

    async def get(self, conversation_id: uuid.UUID) -> Conversation:
        conversation = await self.db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == self.user_id
            )
        )
        if conversation is None:
            raise not_found("conversation")
        return conversation

    async def create(self, body: ConversationCreate) -> Conversation:
        module_id = body.module_id
        if body.topic_id is not None:
            topic = await self.topics.get(body.topic_id)
            if topic is None:
                raise not_found("topic")
            if module_id is not None and module_id != topic.module_id:
                raise AppError("topic_not_in_module", "That topic is in a different module.", 422)
            module_id = topic.module_id
        if module_id is not None and await self.modules.get(module_id) is None:
            raise not_found("module")
        conversation = Conversation(
            id=uuid.uuid4(),
            user_id=self.user_id,
            title=NEW_TITLE,
            module_id=module_id,
            topic_id=body.topic_id,
        )
        self.db.add(conversation)
        await self.db.commit()
        await self.db.refresh(conversation)
        return conversation

    async def detail(self, conversation_id: uuid.UUID) -> ConversationDetail:
        conversation = await self.get(conversation_id)
        messages = (
            await self.db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.created_at, Message.role.desc())
            )
        ).all()
        actions = await PendingActionService(
            self.db, self.user_id, self.client, config=self.config
        ).list_for_messages([m.id for m in messages if m.role == "assistant"])
        by_message: dict[uuid.UUID, list[PendingActionOut]] = {}
        for action in actions:
            if action.message_id is not None:
                by_message.setdefault(action.message_id, []).append(
                    PendingActionOut.model_validate(action)
                )
        return ConversationDetail(
            **ConversationOut.model_validate(conversation).model_dump(),
            messages=[
                MessageOut.model_validate(m).model_copy(
                    update={"actions": by_message.get(m.id, [])}
                )
                for m in messages
            ],
        )

    def check_length(self, text: str) -> None:
        limit = self.config.ai.chat.max_message_chars
        if len(text) > limit:
            raise AppError("message_too_long", f"Messages are limited to {limit} characters.", 422)

    async def name_from_first_message(self, conversation: Conversation, text: str) -> None:
        if conversation.title == NEW_TITLE:
            conversation.title = title_from(text)
            await self.db.commit()

    async def delete(self, conversation_id: uuid.UUID) -> None:
        """Permanent: a conversation is not course material, and its answers
        can be asked again. The UI confirms first."""
        conversation = await self.get(conversation_id)
        await self.db.delete(conversation)
        self._record("conversation_deleted", "conversation", conversation_id)
        await self.db.commit()
