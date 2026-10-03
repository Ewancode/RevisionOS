"""Revision materials and their versions (SPEC 18-20).

A material's content lives in versions that are never edited: editing,
restoring an old version or accepting Claude's improvement all add a new
version, so nothing is ever overwritten. Your materials and Claude's are kept
apart by `origin`.
"""

import builtins
import difflib
import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from app.core.clock import utcnow
from app.core.errors import AppError
from app.models import Material, MaterialVersion
from app.schemas.practice import (
    DiffLine,
    DiffOut,
    MaterialCreate,
    MaterialOut,
    MaterialUpdate,
    VersionOut,
    VersionSummary,
)
from app.services.common import ScopedService, not_found


class MaterialService(ScopedService):
    async def get(self, material_id: uuid.UUID) -> Material:
        material = await self.db.scalar(
            select(Material).where(
                Material.id == material_id,
                Material.user_id == self.user_id,
                Material.deleted_at.is_(None),
            )
        )
        if material is None:
            raise not_found("material")
        return material

    async def list(self, module_id: uuid.UUID) -> Sequence[Material]:
        await self.placement(module_id, None)
        rows = await self.db.scalars(
            select(Material)
            .where(
                Material.user_id == self.user_id,
                Material.module_id == module_id,
                Material.deleted_at.is_(None),
            )
            .order_by(Material.updated_at.desc())
        )
        return rows.all()

    async def _versions(self, material: Material) -> Sequence[MaterialVersion]:
        rows = await self.db.scalars(
            select(MaterialVersion)
            .where(MaterialVersion.material_id == material.id)
            .order_by(MaterialVersion.version_no.desc())
        )
        return rows.all()

    async def out(self, material: Material) -> MaterialOut:
        versions = await self._versions(material)
        current = next(v for v in versions if v.id == material.current_version_id)
        return MaterialOut.model_validate(
            {
                **{
                    k: getattr(material, k)
                    for k in MaterialOut.model_fields
                    if hasattr(material, k)
                },
                "current": VersionOut.model_validate(current),
                "versions": [VersionSummary.model_validate(v) for v in versions],
            }
        )

    async def create(
        self,
        body: MaterialCreate,
        *,
        origin: str = "user",
        citations: builtins.list[dict[str, Any]] | None = None,
        ai_interaction_id: uuid.UUID | None = None,
        change_note: str | None = None,
    ) -> Material:
        await self.placement(body.module_id, body.topic_id)
        material = Material(
            id=uuid.uuid4(),
            user_id=self.user_id,
            module_id=body.module_id,
            topic_id=body.topic_id,
            title=body.title,
            kind=body.kind,
            origin=origin,
        )
        self.db.add(material)
        await self.db.flush()
        await self.add_version(
            material,
            body.content_md,
            created_by=origin,
            citations=citations,
            ai_interaction_id=ai_interaction_id,
            change_note=change_note,
        )
        return material

    async def add_version(
        self,
        material: Material,
        content_md: str,
        *,
        created_by: str,
        change_note: str | None = None,
        citations: builtins.list[dict[str, Any]] | None = None,
        ai_interaction_id: uuid.UUID | None = None,
    ) -> MaterialVersion:
        latest = await self.db.scalar(
            select(func.max(MaterialVersion.version_no)).where(
                MaterialVersion.material_id == material.id
            )
        )
        version = MaterialVersion(
            id=uuid.uuid4(),
            material_id=material.id,
            user_id=self.user_id,
            version_no=(latest or 0) + 1,
            content_md=content_md,
            citations=citations or [],
            created_by=created_by,
            change_note=change_note,
            ai_interaction_id=ai_interaction_id,
        )
        self.db.add(version)
        await self.db.flush()
        material.current_version_id = version.id
        material.updated_at = utcnow()
        await self.db.commit()
        return version

    async def update(self, material_id: uuid.UUID, body: MaterialUpdate) -> Material:
        material = await self.get(material_id)
        changes = body.changes()
        if "topic_id" in changes:
            await self.placement(material.module_id, body.topic_id)
        for key, value in changes.items():
            setattr(material, key, value)
        await self.db.commit()
        await self.db.refresh(material)
        return material

    async def version(self, material_id: uuid.UUID, version_id: uuid.UUID) -> MaterialVersion:
        material = await self.get(material_id)
        version = await self.db.scalar(
            select(MaterialVersion).where(
                MaterialVersion.id == version_id, MaterialVersion.material_id == material.id
            )
        )
        if version is None:
            raise not_found("version")
        return version

    async def restore_version(self, material_id: uuid.UUID, version_id: uuid.UUID) -> Material:
        """Bring back an old version as the newest one (history is kept)."""
        old = await self.version(material_id, version_id)
        material = await self.get(material_id)
        await self.add_version(
            material,
            old.content_md,
            created_by="user",
            change_note=f"Restored version {old.version_no}",
            citations=old.citations,
        )
        return material

    async def delete_version(self, material_id: uuid.UUID, version_id: uuid.UUID) -> None:
        """Permanent; the UI confirms first. The current version cannot be deleted."""
        version = await self.version(material_id, version_id)
        material = await self.get(material_id)
        if version.id == material.current_version_id:
            raise AppError(
                "version_is_current", "Restore another version before deleting this one.", 409
            )
        await self.db.delete(version)
        self._record(
            "material_version_deleted", "material", material.id, version=version.version_no
        )
        await self.db.commit()

    async def diff(self, material_id: uuid.UUID, a: uuid.UUID, b: uuid.UUID) -> DiffOut:
        old, new = await self.version(material_id, a), await self.version(material_id, b)
        lines: builtins.list[DiffLine] = []
        before, after = old.content_md.splitlines(), new.content_md.splitlines()
        matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op == "equal":
                lines.extend(DiffLine(op="equal", text=t) for t in before[i1:i2])
                continue
            lines.extend(DiffLine(op="delete", text=t) for t in before[i1:i2])
            lines.extend(DiffLine(op="insert", text=t) for t in after[j1:j2])
        return DiffOut(from_version=old.version_no, to_version=new.version_no, lines=lines)

    async def delete(self, material_id: uuid.UUID) -> None:
        material = await self.get(material_id)
        material.deleted_at = utcnow()
        self._record("material_deleted", "material", material.id, title=material.title)
        await self.db.commit()

    async def restore(self, material_id: uuid.UUID, since: timedelta) -> Material:
        material = await self.db.scalar(
            select(Material).where(
                Material.id == material_id,
                Material.user_id == self.user_id,
                Material.deleted_at >= utcnow() - since,
            )
        )
        if material is None:
            raise not_found("material")
        material.deleted_at = None
        await self.db.commit()
        await self.db.refresh(material)
        return material
