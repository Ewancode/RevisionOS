import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Module
from app.repositories.identity import AuditRepository
from app.repositories.structure import ModuleRepository, TopicRepository, YearRepository


@dataclass(frozen=True)
class ClientInfo:
    """Who is calling, for the audit log and rate limits."""

    ip: str | None
    user_agent: str | None


def not_found(kind: str) -> AppError:
    # Identical for "missing" and "someone else's", so ids cannot be probed.
    return AppError(f"{kind}_not_found", f"That {kind.replace('_', ' ')} does not exist.", 404)


class ScopedService:
    """Base for services over one user's data: every repository is scoped to
    `user_id`, and destructive actions are written to the audit log."""

    def __init__(self, db: AsyncSession, user_id: uuid.UUID, client: ClientInfo) -> None:
        self.db = db
        self.user_id = user_id
        self.client = client
        self.years = YearRepository(db, user_id)
        self.modules = ModuleRepository(db, user_id)
        self.topics = TopicRepository(db, user_id)
        self.audit = AuditRepository(db)

    async def placement(self, module_id: uuid.UUID, topic_id: uuid.UUID | None) -> Module:
        """The user's live module, after checking the topic (if any) is in it."""
        module = await self.modules.get(module_id)
        if module is None:
            raise not_found("module")
        if topic_id is not None:
            topic = await self.topics.get(topic_id)
            if topic is None or topic.module_id != module_id:
                raise not_found("topic")
        return module

    def _record(
        self, action: str, target_type: str, target_id: uuid.UUID, **details: object
    ) -> None:
        self.audit.record(
            action,
            user_id=self.user_id,
            target_type=target_type,
            target_id=target_id,
            ip=self.client.ip,
            user_agent=self.client.user_agent,
            details=details or None,
        )
