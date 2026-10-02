"""The assistant: conversations, their messages, and delete requests that
wait for the user's confirmation (ARCHITECTURE.md sections 5 and 9)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import CreatedAt, OptionalTimestamp, UpdatedAt, UUIDPk

MESSAGE_ROLES = ("user", "assistant")
# "stopped": you pressed Stop or the connection dropped mid-answer.
MESSAGE_STATUSES = ("complete", "stopped", "error")
PENDING_ACTIONS = ("delete_document", "delete_topic", "delete_module")
PENDING_STATUSES = ("pending", "confirmed", "cancelled", "expired")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    # Where you asked from; searches start there and widen when thin. The
    # owner is checked by the service when these are set.
    module_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("modules.id", ondelete="SET NULL")
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[UUIDPk]
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(Enum(*MESSAGE_ROLES, name="message_role"))
    # Markdown. Assistant answers carry citation markers `[[n]](#cite-n)`
    # that refer to `citations[n-1]`.
    content: Mapped[str] = mapped_column(Text)
    # Only citations the server verified against passages it supplied.
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default="[]", default=list
    )
    # Computed from the citations, never from what Claude says it used:
    # e.g. ["university"], ["university", "own"], or ["general"].
    provenance: Mapped[list[str]] = mapped_column(JSONB, server_default="[]", default=list)
    # What the assistant did on the way ("Searched your materials for ...").
    steps: Mapped[list[str]] = mapped_column(JSONB, server_default="[]", default=list)
    status: Mapped[str] = mapped_column(
        Enum(*MESSAGE_STATUSES, name="message_status"), server_default="complete"
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[CreatedAt]

    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)


class PendingAction(Base):
    """A destructive request from Claude. Nothing happens until you confirm it
    yourself (POST /pending-actions/{id}/confirm); no tool can do that."""

    __tablename__ = "pending_actions"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    # The assistant message that asked; it is saved when the answer ends.
    message_id: Mapped[uuid.UUID | None]
    action: Mapped[str] = mapped_column(Enum(*PENDING_ACTIONS, name="pending_action_kind"))
    target_id: Mapped[uuid.UUID]
    # Human-readable, built by the server from the target ("Delete ...?").
    preview: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Enum(*PENDING_STATUSES, name="pending_action_status"), server_default="pending"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[OptionalTimestamp]
    created_at: Mapped[CreatedAt]

    __table_args__ = (Index("ix_pending_actions_user_message", "user_id", "message_id"),)
