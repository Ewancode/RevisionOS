"""Revision materials with version history, and drafts of generated content
(SPEC 18-20 and 40)."""

import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import Client, Config, CurrentUser, DbSession, rate_limited
from app.schemas.practice import (
    DiffOut,
    DraftOut,
    DraftRegenerate,
    DraftSave,
    GenerateRequest,
    MaterialCreate,
    MaterialOut,
    MaterialSummary,
    MaterialUpdate,
    SavedDraft,
    VersionCreate,
    VersionOut,
)
from app.services.drafts import DraftService, draft_out
from app.services.materials import MaterialService

router = APIRouter(tags=["materials"])


def _materials(db: DbSession, user: CurrentUser, client: Client) -> MaterialService:
    return MaterialService(db, user.id, client)


def _drafts(
    request: Request, db: DbSession, user: CurrentUser, client: Client, config: Config
) -> DraftService:
    return DraftService(db, user.id, client, config=config, jobs=request.app.state.jobs)


Materials = Annotated[MaterialService, Depends(_materials)]
Drafts = Annotated[DraftService, Depends(_drafts)]


# --- drafts ------------------------------------------------------------------------------


@router.post(
    "/drafts",
    response_model=DraftOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[rate_limited("ai")],
)
async def generate(body: GenerateRequest, drafts: Drafts) -> DraftOut:
    """Ask Claude for a material, questions or flashcards. Poll the draft
    until it is ready, then save, regenerate or discard it."""
    return draft_out(await drafts.create(body))


@router.get("/drafts", response_model=list[DraftOut])
async def list_drafts(module_id: uuid.UUID, drafts: Drafts) -> list[DraftOut]:
    """Drafts not yet saved or discarded."""
    return [draft_out(d) for d in await drafts.list(module_id)]


@router.get("/drafts/{draft_id}", response_model=DraftOut)
async def get_draft(draft_id: uuid.UUID, drafts: Drafts) -> DraftOut:
    return draft_out(await drafts.get(draft_id))


@router.post("/drafts/{draft_id}/save", response_model=SavedDraft)
async def save_draft(draft_id: uuid.UUID, body: DraftSave, drafts: Drafts) -> SavedDraft:
    return await drafts.save(draft_id, body)


@router.post(
    "/drafts/{draft_id}/regenerate",
    response_model=DraftOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[rate_limited("ai")],
)
async def regenerate_draft(draft_id: uuid.UUID, body: DraftRegenerate, drafts: Drafts) -> DraftOut:
    return draft_out(await drafts.regenerate(draft_id, body.instructions))


@router.post("/drafts/{draft_id}/discard", response_model=DraftOut)
async def discard_draft(draft_id: uuid.UUID, drafts: Drafts) -> DraftOut:
    return draft_out(await drafts.discard(draft_id))


# --- materials -------------------------------------------------------------------------


@router.get("/materials", response_model=list[MaterialSummary])
async def list_materials(module_id: uuid.UUID, materials: Materials) -> list[MaterialSummary]:
    return [MaterialSummary.model_validate(m) for m in await materials.list(module_id)]


@router.post("/materials", response_model=MaterialOut, status_code=status.HTTP_201_CREATED)
async def create_material(body: MaterialCreate, materials: Materials) -> MaterialOut:
    """One of your own materials (origin: user)."""
    return await materials.out(await materials.create(body))


@router.get("/materials/{material_id}", response_model=MaterialOut)
async def get_material(material_id: uuid.UUID, materials: Materials) -> MaterialOut:
    return await materials.out(await materials.get(material_id))


@router.patch("/materials/{material_id}", response_model=MaterialOut)
async def update_material(
    material_id: uuid.UUID, body: MaterialUpdate, materials: Materials
) -> MaterialOut:
    return await materials.out(await materials.update(material_id, body))


@router.delete("/materials/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_material(material_id: uuid.UUID, materials: Materials) -> None:
    await materials.delete(material_id)


@router.post("/materials/{material_id}/restore", response_model=MaterialOut)
async def restore_material(
    material_id: uuid.UUID, materials: Materials, config: Config
) -> MaterialOut:
    retention = timedelta(days=config.platform.trash.retention_days)
    return await materials.out(await materials.restore(material_id, retention))


@router.post(
    "/materials/{material_id}/versions",
    response_model=MaterialOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_version(
    material_id: uuid.UUID, body: VersionCreate, materials: Materials
) -> MaterialOut:
    """Your edit, saved as a new version (the old ones are kept)."""
    material = await materials.get(material_id)
    await materials.add_version(
        material, body.content_md, created_by="user", change_note=body.change_note
    )
    return await materials.out(material)


@router.get("/materials/{material_id}/versions/{version_id}", response_model=VersionOut)
async def get_version(
    material_id: uuid.UUID, version_id: uuid.UUID, materials: Materials
) -> VersionOut:
    return VersionOut.model_validate(await materials.version(material_id, version_id))


@router.post("/materials/{material_id}/versions/{version_id}/restore", response_model=MaterialOut)
async def restore_version(
    material_id: uuid.UUID, version_id: uuid.UUID, materials: Materials
) -> MaterialOut:
    return await materials.out(await materials.restore_version(material_id, version_id))


@router.delete(
    "/materials/{material_id}/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_version(
    material_id: uuid.UUID, version_id: uuid.UUID, materials: Materials
) -> None:
    await materials.delete_version(material_id, version_id)


@router.get("/materials/{material_id}/diff", response_model=DiffOut)
async def diff_versions(
    material_id: uuid.UUID, from_version: uuid.UUID, to_version: uuid.UUID, materials: Materials
) -> DiffOut:
    return await materials.diff(material_id, from_version, to_version)
