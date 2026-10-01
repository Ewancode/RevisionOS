"""User-scoped access to years, modules and topics.

A row belonging to another user is indistinguishable from a missing row:
both come back as None, which the services turn into 404.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import AcademicYear, Module, Topic


class _Scoped:
    def __init__(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        self.db = db
        self.user_id = user_id


class YearRepository(_Scoped):
    async def list(self) -> Sequence[AcademicYear]:
        stmt = (
            select(AcademicYear)
            .where(AcademicYear.user_id == self.user_id)
            .order_by(AcademicYear.start_date.desc())
        )
        return (await self.db.scalars(stmt)).all()

    async def get(self, year_id: uuid.UUID) -> AcademicYear | None:
        return await self.db.scalar(
            select(AcademicYear).where(
                AcademicYear.id == year_id, AcademicYear.user_id == self.user_id
            )
        )

    async def count(self) -> int:
        stmt = select(func.count()).where(AcademicYear.user_id == self.user_id)
        return int(await self.db.scalar(stmt) or 0)

    async def clear_current(self) -> None:
        await self.db.execute(
            update(AcademicYear)
            .where(AcademicYear.user_id == self.user_id, AcademicYear.is_current)
            .values(is_current=False)
        )
        # The partial unique index is checked per statement, so flush before
        # another row is marked current.
        await self.db.flush()

    async def has_modules(self, year_id: uuid.UUID) -> bool:
        """Counts modules in the trash too: deleting the year would destroy them."""
        stmt = select(
            select(Module.id)
            .where(Module.user_id == self.user_id, Module.academic_year_id == year_id)
            .exists()
        )
        return bool(await self.db.scalar(stmt))


class ModuleRepository(_Scoped):
    def _live(self) -> Select[Module]:
        return select(Module).where(Module.user_id == self.user_id, Module.deleted_at.is_(None))

    async def list(self, *, year_id: uuid.UUID | None, statuses: Sequence[str]) -> Sequence[Module]:
        stmt = self._live().where(Module.status.in_(statuses)).order_by(Module.code)
        if year_id is not None:
            stmt = stmt.where(Module.academic_year_id == year_id)
        return (await self.db.scalars(stmt)).all()

    async def get(self, module_id: uuid.UUID) -> Module | None:
        return await self.db.scalar(self._live().where(Module.id == module_id))

    async def get_deleted(self, module_id: uuid.UUID, since: datetime) -> Module | None:
        return await self.db.scalar(
            select(Module).where(
                Module.id == module_id,
                Module.user_id == self.user_id,
                Module.deleted_at >= since,
            )
        )

    async def list_deleted(self, since: datetime) -> Sequence[Module]:
        stmt = (
            select(Module)
            .where(Module.user_id == self.user_id, Module.deleted_at >= since)
            .order_by(Module.deleted_at.desc())
        )
        return (await self.db.scalars(stmt)).all()


class TopicRepository(_Scoped):
    def _live(self) -> Select[Topic]:
        """Live topics in live modules."""
        return (
            select(Topic)
            .join(Module, Module.id == Topic.module_id)
            .where(
                Topic.user_id == self.user_id,
                Topic.deleted_at.is_(None),
                Module.deleted_at.is_(None),
            )
        )

    async def get(self, topic_id: uuid.UUID) -> Topic | None:
        return await self.db.scalar(self._live().where(Topic.id == topic_id))

    async def list_for_module(self, module_id: uuid.UUID) -> Sequence[Topic]:
        stmt = (
            self._live()
            .where(Topic.module_id == module_id)
            .order_by(Topic.parent_id.nulls_first(), Topic.position, Topic.created_at)
        )
        return (await self.db.scalars(stmt)).all()

    async def siblings(self, module_id: uuid.UUID, parent_id: uuid.UUID | None) -> list[Topic]:
        stmt = self._live().where(Topic.module_id == module_id)
        stmt = stmt.where(
            Topic.parent_id.is_(None) if parent_id is None else Topic.parent_id == parent_id
        )
        return list((await self.db.scalars(stmt.order_by(Topic.position, Topic.created_at))).all())

    async def subtree_ids(
        self, root_id: uuid.UUID, *, deleted_at: datetime | None
    ) -> list[uuid.UUID]:
        """The root and all descendants sharing its deletion state.

        With ``deleted_at=None`` this is the live subtree; with a timestamp it
        is the part of the subtree deleted in that same operation.
        """
        state = Topic.deleted_at.is_(None) if deleted_at is None else Topic.deleted_at == deleted_at
        base = (
            select(Topic.id)
            .where(Topic.id == root_id, Topic.user_id == self.user_id, state)
            .cte("subtree", recursive=True)
        )
        child = aliased(Topic)
        tree = base.union_all(
            select(child.id)
            .join(base, child.parent_id == base.c.id)
            .where(
                child.user_id == self.user_id,
                child.deleted_at.is_(None)
                if deleted_at is None
                else child.deleted_at == deleted_at,
            )
        )
        return list((await self.db.scalars(select(tree.c.id))).all())

    async def set_deleted_at(self, ids: Sequence[uuid.UUID], value: datetime | None) -> None:
        await self.db.execute(
            update(Topic)
            .where(Topic.user_id == self.user_id, Topic.id.in_(ids))
            .values(deleted_at=value)
        )

    async def get_deleted(self, topic_id: uuid.UUID, since: datetime) -> Topic | None:
        return await self.db.scalar(
            select(Topic)
            .join(Module, Module.id == Topic.module_id)
            .where(
                Topic.id == topic_id,
                Topic.user_id == self.user_id,
                Topic.deleted_at >= since,
                Module.deleted_at.is_(None),
            )
        )

    async def get_any(self, topic_id: uuid.UUID) -> Topic | None:
        """Owned topic regardless of deletion state (for restore checks)."""
        return await self.db.scalar(
            select(Topic).where(Topic.id == topic_id, Topic.user_id == self.user_id)
        )

    async def list_deleted_roots(self, since: datetime) -> Sequence[Topic]:
        """Deleted topics whose parent was not deleted in the same operation
        — the units a user can restore. Topics of trashed modules are hidden;
        restoring the module brings them back."""
        parent = aliased(Topic)
        stmt = (
            select(Topic)
            .join(Module, Module.id == Topic.module_id)
            .outerjoin(parent, parent.id == Topic.parent_id)
            .where(
                Topic.user_id == self.user_id,
                Topic.deleted_at >= since,
                Module.deleted_at.is_(None),
                (parent.id.is_(None)) | (parent.deleted_at.is_distinct_from(Topic.deleted_at)),
            )
            .order_by(Topic.deleted_at.desc())
        )
        return (await self.db.scalars(stmt)).all()
