"""Deletes Claude asked for, waiting for the user (ARCHITECTURE.md section 9).

Claude's tools can only *create* a pending action. Carrying it out takes a
separate request from the user's signed-in browser, with a CSRF token, to
`POST /pending-actions/{id}/confirm`; nothing on the AI side can call that.
The delete itself is the ordinary soft delete, so even a confirmed mistake
can be restored from the trash.
"""

import uuid
from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import AppConfig
from app.core.errors import AppError
from app.models import Document, PendingAction
from app.services.common import ClientInfo, ScopedService, not_found
from app.services.documents import DocumentService
from app.services.structure import ModuleService, TopicService


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class PendingActionService(ScopedService):
    def __init__(
        self, db: AsyncSession, user_id: uuid.UUID, client: ClientInfo, *, config: AppConfig
    ) -> None:
        super().__init__(db, user_id, client)
        self.config = config

    @property
    def _restore_note(self) -> str:
        days = self.config.platform.trash.retention_days
        return f"It moves to the trash, where you can restore it from Settings for {days} days."

    async def _create(
        self,
        action: str,
        target_id: uuid.UUID,
        preview: str,
        conversation_id: uuid.UUID | None,
        message_id: uuid.UUID | None,
    ) -> PendingAction:
        minutes = self.config.ai.chat.pending_action_minutes
        pending = PendingAction(
            id=uuid.uuid4(),
            user_id=self.user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            action=action,
            target_id=target_id,
            preview=preview,
            status="pending",
            expires_at=utcnow() + timedelta(minutes=minutes),
        )
        self.db.add(pending)
        await self.db.commit()
        return pending

    # --- requests (from Claude's tools) -----------------------------------------

    async def request_delete_document(
        self,
        document_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
        message_id: uuid.UUID | None,
    ) -> PendingAction:
        doc = await self.db.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.user_id == self.user_id,
                Document.deleted_at.is_(None),
            )
        )
        if doc is None:
            raise not_found("document")
        preview = f"Delete “{doc.original_filename}”? {self._restore_note}"
        return await self._create("delete_document", doc.id, preview, conversation_id, message_id)

    async def request_delete_topic(
        self, topic_id: uuid.UUID, conversation_id: uuid.UUID | None, message_id: uuid.UUID | None
    ) -> PendingAction:
        topic = await self.topics.get(topic_id)
        if topic is None:
            raise not_found("topic")
        below = len(await self.topics.subtree_ids(topic.id, deleted_at=None)) - 1
        inside = f", with its {_plural(below, 'subtopic')}" if below else ""
        preview = f"Delete the topic “{topic.title}”{inside}? {self._restore_note}"
        return await self._create("delete_topic", topic.id, preview, conversation_id, message_id)

    async def request_delete_module(
        self, module_id: uuid.UUID, conversation_id: uuid.UUID | None, message_id: uuid.UUID | None
    ) -> PendingAction:
        module = await self.modules.get(module_id)
        if module is None:
            raise not_found("module")
        files = await self.db.scalar(
            select(func.count()).where(
                Document.module_id == module.id,
                Document.user_id == self.user_id,
                Document.deleted_at.is_(None),
            )
        )
        preview = (
            f"Delete the module {module.code} {module.title}, with its topics and "
            f"{_plural(files or 0, 'file')}? {self._restore_note}"
        )
        return await self._create("delete_module", module.id, preview, conversation_id, message_id)

    # --- the user's decision -------------------------------------------------------

    async def list_for_messages(self, message_ids: Sequence[uuid.UUID]) -> list[PendingAction]:
        if not message_ids:
            return []
        rows = await self.db.scalars(
            select(PendingAction)
            .where(PendingAction.user_id == self.user_id, PendingAction.message_id.in_(message_ids))
            .order_by(PendingAction.created_at)
        )
        actions = list(rows.all())
        await self._expire_stale(actions)
        return actions

    async def _expire_stale(self, actions: Sequence[PendingAction]) -> None:
        now = utcnow()
        stale = [a for a in actions if a.status == "pending" and a.expires_at <= now]
        for action in stale:
            action.status, action.resolved_at = "expired", now
        if stale:
            await self.db.commit()

    async def _get_pending(self, action_id: uuid.UUID) -> PendingAction:
        action = await self.db.scalar(
            select(PendingAction).where(
                PendingAction.id == action_id, PendingAction.user_id == self.user_id
            )
        )
        if action is None:
            raise not_found("pending_action")
        await self._expire_stale([action])
        if action.status != "pending":
            raise AppError(
                "action_not_pending",
                f"This request is already {action.status}; ask again if you still want it.",
                409,
            )
        return action

    async def confirm(
        self,
        action_id: uuid.UUID,
        documents: DocumentService,
        modules: ModuleService,
        topics: TopicService,
    ) -> PendingAction:
        action = await self._get_pending(action_id)
        if action.action == "delete_document":
            await documents.delete(action.target_id)
        elif action.action == "delete_topic":
            await topics.delete(action.target_id)
        else:
            await modules.delete(action.target_id)
        action.status, action.resolved_at = "confirmed", utcnow()
        self._record("pending_action_confirmed", action.action, action.target_id)
        await self.db.commit()
        return action

    async def cancel(self, action_id: uuid.UUID) -> PendingAction:
        action = await self._get_pending(action_id)
        action.status, action.resolved_at = "cancelled", utcnow()
        await self.db.commit()
        return action
