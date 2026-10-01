"""Users, sessions and the audit log.

These are looked up by email or token *before* a user is known, so they are
not user-scoped; nothing here is reachable with a client-supplied user id.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, AuthSession, User


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def by_email(self, email: str) -> User | None:
        return await self.db.scalar(select(User).where(User.email == email.lower()))

    async def by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.db.get(User, user_id)


class SessionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def by_token_hash(self, token_hash: bytes) -> AuthSession | None:
        return await self.db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))

    async def revoke_all_for_user(
        self, user_id: uuid.UUID, at: datetime, *, except_id: uuid.UUID | None = None
    ) -> None:
        stmt = update(AuthSession).where(
            AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
        )
        if except_id is not None:
            stmt = stmt.where(AuthSession.id != except_id)
        await self.db.execute(stmt.values(revoked_at=at))


class AuditRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def record(
        self,
        action: str,
        *,
        user_id: uuid.UUID | None,
        target_type: str | None = None,
        target_id: uuid.UUID | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.db.add(
            AuditLog(
                action=action,
                user_id=user_id,
                target_type=target_type,
                target_id=target_id,
                ip=ip,
                user_agent=user_agent,
                details=details,
            )
        )
