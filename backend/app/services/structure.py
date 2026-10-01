"""Academic years, modules and the topic tree."""

import uuid
from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import TrashConfig
from app.core.errors import AppError
from app.models import AcademicYear, Module, Topic
from app.repositories.identity import AuditRepository
from app.repositories.structure import ModuleRepository, TopicRepository, YearRepository
from app.schemas.structure import (
    ModuleCreate,
    ModuleUpdate,
    TopicCreate,
    TopicMove,
    TopicNode,
    TopicUpdate,
    TrashedModule,
    TrashedTopic,
    TrashOut,
    YearCreate,
    YearUpdate,
)
from app.services.common import ClientInfo, not_found

CODE_TAKEN_CONSTRAINT = "uq_modules_year_code_live"


def _code_taken(code: str) -> AppError:
    return AppError("module_code_taken", f"This year already has a module {code}.", 409)


def _is_violation(exc: IntegrityError, constraint: str) -> bool:
    return constraint in str(exc.orig)


class _Service:
    def __init__(self, db: AsyncSession, user_id: uuid.UUID, client: ClientInfo) -> None:
        self.db = db
        self.user_id = user_id
        self.client = client
        self.years = YearRepository(db, user_id)
        self.modules = ModuleRepository(db, user_id)
        self.topics = TopicRepository(db, user_id)
        self.audit = AuditRepository(db)

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


# --- years -------------------------------------------------------------------


class YearService(_Service):
    async def list(self) -> Sequence[AcademicYear]:
        return await self.years.list()

    async def _get(self, year_id: uuid.UUID) -> AcademicYear:
        year = await self.years.get(year_id)
        if year is None:
            raise not_found("academic_year")
        return year

    async def create(self, body: YearCreate) -> AcademicYear:
        # The first year is current automatically; later ones only if asked.
        make_current = body.is_current or await self.years.count() == 0
        if make_current:
            await self.years.clear_current()
        year = AcademicYear(
            user_id=self.user_id,
            label=body.label,
            start_date=body.start_date,
            end_date=body.end_date,
            is_current=make_current,
        )
        self.db.add(year)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise AppError(
                "year_label_taken", f"You already have a year '{body.label}'.", 409
            ) from exc
        return year

    async def update(self, year_id: uuid.UUID, body: YearUpdate) -> AcademicYear:
        year = await self._get(year_id)
        for field, value in body.changes().items():
            setattr(year, field, value)
        if year.end_date <= year.start_date:
            raise AppError("validation_error", "The end date must be after the start date.", 422)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise AppError(
                "year_label_taken", "You already have a year with that label.", 409
            ) from exc
        return year

    async def make_current(self, year_id: uuid.UUID) -> AcademicYear:
        year = await self._get(year_id)
        await self.years.clear_current()
        year.is_current = True
        await self.db.commit()
        return year

    async def delete(self, year_id: uuid.UUID) -> None:
        year = await self._get(year_id)
        if await self.years.has_modules(year_id):
            raise AppError(
                "year_not_empty",
                "This year still has modules (including any in the trash). Remove them first.",
                409,
            )
        await self.db.delete(year)
        self._record("year_deleted", "academic_year", year_id, label=year.label)
        await self.db.commit()


# --- modules -----------------------------------------------------------------


class ModuleService(_Service):
    async def list(self, year_id: uuid.UUID | None, statuses: Sequence[str]) -> Sequence[Module]:
        return await self.modules.list(year_id=year_id, statuses=statuses)

    async def get(self, module_id: uuid.UUID) -> Module:
        module = await self.modules.get(module_id)
        if module is None:
            raise not_found("module")
        return module

    async def create(self, body: ModuleCreate) -> Module:
        if await self.years.get(body.academic_year_id) is None:
            raise not_found("academic_year")
        module = Module(user_id=self.user_id, **body.model_dump())
        self.db.add(module)
        await self._commit_or_code_taken(body.code)
        return module

    async def update(self, module_id: uuid.UUID, body: ModuleUpdate) -> Module:
        module = await self.get(module_id)
        for field, value in body.changes().items():
            setattr(module, field, value)
        await self._commit_or_code_taken(module.code)
        return module

    async def delete(self, module_id: uuid.UUID) -> None:
        module = await self.get(module_id)
        module.deleted_at = utcnow()
        self._record("module_deleted", "module", module_id, code=module.code)
        await self.db.commit()

    async def restore(self, module_id: uuid.UUID, since: timedelta) -> Module:
        module = await self.modules.get_deleted(module_id, utcnow() - since)
        if module is None:
            raise not_found("module")
        module.deleted_at = None
        self._record("module_restored", "module", module_id, code=module.code)
        await self._commit_or_code_taken(module.code)
        return module

    async def _commit_or_code_taken(self, code: str) -> None:
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            if _is_violation(exc, CODE_TAKEN_CONSTRAINT):
                raise _code_taken(code) from exc
            raise


# --- topics ------------------------------------------------------------------


def build_tree(topics: Sequence[Topic]) -> list[TopicNode]:
    """Nest a flat, position-ordered list of one module's live topics."""
    nodes = {t.id: TopicNode.model_validate(t) for t in topics}
    roots: list[TopicNode] = []
    for topic in topics:
        node = nodes[topic.id]
        parent = nodes.get(topic.parent_id) if topic.parent_id else None
        (parent.children if parent else roots).append(node)
    return roots


def _renumber(siblings: list[Topic]) -> None:
    for index, sibling in enumerate(siblings):
        sibling.position = index


class TopicService(_Service):
    async def _module(self, module_id: uuid.UUID) -> Module:
        module = await self.modules.get(module_id)
        if module is None:
            raise not_found("module")
        return module

    async def get(self, topic_id: uuid.UUID) -> Topic:
        topic = await self.topics.get(topic_id)
        if topic is None:
            raise not_found("topic")
        return topic

    async def tree(self, module_id: uuid.UUID) -> list[TopicNode]:
        await self._module(module_id)
        return build_tree(await self.topics.list_for_module(module_id))

    async def _parent_in(self, module_id: uuid.UUID, parent_id: uuid.UUID | None) -> None:
        if parent_id is None:
            return
        parent = await self.topics.get(parent_id)
        if parent is None or parent.module_id != module_id:
            raise not_found("parent_topic")

    async def create(self, module_id: uuid.UUID, body: TopicCreate) -> Topic:
        await self._module(module_id)
        await self._parent_in(module_id, body.parent_id)
        siblings = await self.topics.siblings(module_id, body.parent_id)
        topic = Topic(
            user_id=self.user_id,
            module_id=module_id,
            parent_id=body.parent_id,
            title=body.title,
            importance=body.importance,
            position=len(siblings),
        )
        self.db.add(topic)
        await self.db.commit()
        return topic

    async def update(self, topic_id: uuid.UUID, body: TopicUpdate) -> Topic:
        topic = await self.get(topic_id)
        for field, value in body.changes().items():
            setattr(topic, field, value)
        await self.db.commit()
        return topic

    async def move(self, topic_id: uuid.UUID, body: TopicMove) -> Topic:
        topic = await self.get(topic_id)
        await self._parent_in(topic.module_id, body.parent_id)
        if body.parent_id is not None:
            subtree = await self.topics.subtree_ids(topic.id, deleted_at=None)
            if body.parent_id in subtree:
                raise AppError(
                    "invalid_move", "A topic cannot be moved inside itself or its subtopics.", 422
                )

        old = [
            s
            for s in await self.topics.siblings(topic.module_id, topic.parent_id)
            if s.id != topic.id
        ]
        _renumber(old)
        new = (
            old
            if body.parent_id == topic.parent_id
            else await self.topics.siblings(topic.module_id, body.parent_id)
        )
        new.insert(min(body.position, len(new)), topic)
        topic.parent_id = body.parent_id
        _renumber(new)
        await self.db.commit()
        return topic

    async def delete(self, topic_id: uuid.UUID) -> None:
        topic = await self.get(topic_id)
        ids = await self.topics.subtree_ids(topic.id, deleted_at=None)
        await self.topics.set_deleted_at(ids, utcnow())
        siblings = [
            s
            for s in await self.topics.siblings(topic.module_id, topic.parent_id)
            if s.id != topic.id
        ]
        _renumber(siblings)
        self._record("topic_deleted", "topic", topic_id, title=topic.title, subtree_size=len(ids))
        await self.db.commit()

    async def restore(self, topic_id: uuid.UUID, since: timedelta) -> Topic:
        topic = await self.topics.get_deleted(topic_id, utcnow() - since)
        if topic is None or topic.deleted_at is None:
            raise not_found("topic")
        if topic.parent_id is not None and await self.topics.get(topic.parent_id) is None:
            raise AppError(
                "parent_deleted", "Restore the parent topic first; this one belongs under it.", 409
            )
        ids = await self.topics.subtree_ids(topic.id, deleted_at=topic.deleted_at)
        siblings = await self.topics.siblings(topic.module_id, topic.parent_id)
        await self.topics.set_deleted_at(ids, None)
        topic.position = len(siblings)
        self._record("topic_restored", "topic", topic_id, title=topic.title)
        await self.db.commit()
        await self.db.refresh(topic)
        return topic


# --- trash -------------------------------------------------------------------


class TrashService(_Service):
    async def list(self, config: TrashConfig) -> TrashOut:
        since = utcnow() - timedelta(days=config.retention_days)
        modules = await self.modules.list_deleted(since)
        topics = await self.topics.list_deleted_roots(since)
        return TrashOut(
            retention_days=config.retention_days,
            modules=[TrashedModule.model_validate(m) for m in modules],
            topics=[TrashedTopic.model_validate(t) for t in topics],
        )
