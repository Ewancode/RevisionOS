"""Every Claude call and its cost (ARCHITECTURE.md section 8)."""

import uuid
from typing import Any

from sqlalchemy import BigInteger, Enum, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import CreatedAt, UUIDPk

INTERACTION_STATUSES = ("ok", "refused", "error", "budget_blocked")


class AIInteraction(Base):
    __tablename__ = "ai_interactions"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    feature: Mapped[str] = mapped_column(String(64))
    # The model that was asked, and the one that answered (they differ when a
    # server-side fallback ran).
    requested_model: Mapped[str] = mapped_column(String(100))
    served_model: Mapped[str | None] = mapped_column(String(100))
    effort: Mapped[str | None] = mapped_column(String(10))
    prompt_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(Enum(*INTERACTION_STATUSES, name="ai_interaction_status"))
    stop_reason: Mapped[str | None] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    request_id: Mapped[str | None] = mapped_column(String(100))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    # Tools Claude asked for in this call: [{"name": ..., "input": {...}}].
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[CreatedAt]

    __table_args__ = (Index("ix_ai_interactions_user_created", "user_id", "created_at"),)


class AIUsage(Base):
    """Tokens and estimated cost of one call. Append-only; budgets sum it."""

    __tablename__ = "ai_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    interaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_interactions.id", ondelete="CASCADE")
    )
    feature: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(100))
    module_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("modules.id", ondelete="SET NULL")
    )
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float)
    created_at: Mapped[CreatedAt]

    __table_args__ = (Index("ix_ai_usage_user_created", "user_id", "created_at"),)
