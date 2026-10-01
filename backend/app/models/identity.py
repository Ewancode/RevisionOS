"""Users, their settings, login sessions and the audit log."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import CreatedAt, OptionalTimestamp, UpdatedAt, UUIDPk

THEMES = ("light", "dark", "system")


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUIDPk]
    # Stored lower-cased; uniqueness is therefore case-insensitive.
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    settings: Mapped["UserSettings"] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="joined"
    )

    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lowercase"),)


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    theme: Mapped[str] = mapped_column(
        Enum(*THEMES, name="theme"), server_default="system", default="system"
    )
    accent_colour: Mapped[str] = mapped_column(
        String(7), server_default="#4f46e5", default="#4f46e5"
    )
    updated_at: Mapped[UpdatedAt]

    user: Mapped[User] = relationship(back_populates="settings")

    __table_args__ = (
        CheckConstraint("accent_colour ~ '^#[0-9a-f]{6}$'", name="accent_colour_hex"),
    )


class AuthSession(Base):
    """A login session. Only SHA-256 hashes of the tokens are stored."""

    __tablename__ = "auth_sessions"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    csrf_token_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    created_at: Mapped[CreatedAt]
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[OptionalTimestamp]
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))


class AuditLog(Base):
    """Append-only record of logins and destructive actions."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[uuid.UUID | None]
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[CreatedAt]
