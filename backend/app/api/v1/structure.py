"""Academic years, modules, topics and the trash."""

import uuid
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Client, Config, CurrentUser, DbSession
from app.schemas.structure import (
    ModuleCreate,
    ModuleOut,
    ModuleUpdate,
    TopicCreate,
    TopicMove,
    TopicNode,
    TopicOut,
    TopicUpdate,
    TrashOut,
    YearCreate,
    YearOut,
    YearUpdate,
)
from app.services.structure import ModuleService, TopicService, TrashService, YearService

router = APIRouter()
NO_CONTENT = status.HTTP_204_NO_CONTENT


def _years(db: DbSession, user: CurrentUser, client: Client) -> YearService:
    return YearService(db, user.id, client)


def _modules(db: DbSession, user: CurrentUser, client: Client) -> ModuleService:
    return ModuleService(db, user.id, client)


def _topics(db: DbSession, user: CurrentUser, client: Client) -> TopicService:
    return TopicService(db, user.id, client)


def _trash(db: DbSession, user: CurrentUser, client: Client) -> TrashService:
    return TrashService(db, user.id, client)


Years = Annotated[YearService, Depends(_years)]
Modules = Annotated[ModuleService, Depends(_modules)]
Topics = Annotated[TopicService, Depends(_topics)]
Trash = Annotated[TrashService, Depends(_trash)]


def _retention(config: Config) -> timedelta:
    return timedelta(days=config.platform.trash.retention_days)


# --- years -------------------------------------------------------------------


@router.get("/years", response_model=list[YearOut], tags=["years"])
async def list_years(years: Years) -> list[YearOut]:
    return [YearOut.model_validate(y) for y in await years.list()]


@router.post("/years", response_model=YearOut, status_code=201, tags=["years"])
async def create_year(body: YearCreate, years: Years) -> YearOut:
    return YearOut.model_validate(await years.create(body))


@router.patch("/years/{year_id}", response_model=YearOut, tags=["years"])
async def update_year(year_id: uuid.UUID, body: YearUpdate, years: Years) -> YearOut:
    return YearOut.model_validate(await years.update(year_id, body))


@router.post("/years/{year_id}/make-current", response_model=YearOut, tags=["years"])
async def make_year_current(year_id: uuid.UUID, years: Years) -> YearOut:
    return YearOut.model_validate(await years.make_current(year_id))


@router.delete("/years/{year_id}", status_code=NO_CONTENT, tags=["years"])
async def delete_year(year_id: uuid.UUID, years: Years) -> None:
    await years.delete(year_id)


# --- modules -----------------------------------------------------------------

StatusFilter = Literal["active", "archived", "all"]


@router.get("/modules", response_model=list[ModuleOut], tags=["modules"])
async def list_modules(
    modules: Modules,
    year_id: uuid.UUID | None = None,
    status_filter: Annotated[StatusFilter, Query(alias="status")] = "active",
) -> list[ModuleOut]:
    statuses = ("active", "archived") if status_filter == "all" else (status_filter,)
    return [ModuleOut.model_validate(m) for m in await modules.list(year_id, statuses)]


@router.post("/modules", response_model=ModuleOut, status_code=201, tags=["modules"])
async def create_module(body: ModuleCreate, modules: Modules) -> ModuleOut:
    return ModuleOut.model_validate(await modules.create(body))


@router.get("/modules/{module_id}", response_model=ModuleOut, tags=["modules"])
async def get_module(module_id: uuid.UUID, modules: Modules) -> ModuleOut:
    return ModuleOut.model_validate(await modules.get(module_id))


@router.patch("/modules/{module_id}", response_model=ModuleOut, tags=["modules"])
async def update_module(module_id: uuid.UUID, body: ModuleUpdate, modules: Modules) -> ModuleOut:
    return ModuleOut.model_validate(await modules.update(module_id, body))


@router.delete("/modules/{module_id}", status_code=NO_CONTENT, tags=["modules"])
async def delete_module(module_id: uuid.UUID, modules: Modules) -> None:
    """Moves the module (and its topics) to the trash."""
    await modules.delete(module_id)


@router.post("/modules/{module_id}/restore", response_model=ModuleOut, tags=["modules"])
async def restore_module(module_id: uuid.UUID, modules: Modules, config: Config) -> ModuleOut:
    return ModuleOut.model_validate(await modules.restore(module_id, _retention(config)))


# --- topics ------------------------------------------------------------------


@router.get("/modules/{module_id}/topics", response_model=list[TopicNode], tags=["topics"])
async def topic_tree(module_id: uuid.UUID, topics: Topics) -> list[TopicNode]:
    return await topics.tree(module_id)


@router.post(
    "/modules/{module_id}/topics", response_model=TopicOut, status_code=201, tags=["topics"]
)
async def create_topic(module_id: uuid.UUID, body: TopicCreate, topics: Topics) -> TopicOut:
    return TopicOut.model_validate(await topics.create(module_id, body))


@router.patch("/topics/{topic_id}", response_model=TopicOut, tags=["topics"])
async def update_topic(topic_id: uuid.UUID, body: TopicUpdate, topics: Topics) -> TopicOut:
    return TopicOut.model_validate(await topics.update(topic_id, body))


@router.post("/topics/{topic_id}/move", response_model=TopicOut, tags=["topics"])
async def move_topic(topic_id: uuid.UUID, body: TopicMove, topics: Topics) -> TopicOut:
    return TopicOut.model_validate(await topics.move(topic_id, body))


@router.delete("/topics/{topic_id}", status_code=NO_CONTENT, tags=["topics"])
async def delete_topic(topic_id: uuid.UUID, topics: Topics) -> None:
    """Moves the topic and its subtopics to the trash."""
    await topics.delete(topic_id)


@router.post("/topics/{topic_id}/restore", response_model=TopicOut, tags=["topics"])
async def restore_topic(topic_id: uuid.UUID, topics: Topics, config: Config) -> TopicOut:
    return TopicOut.model_validate(await topics.restore(topic_id, _retention(config)))


# --- trash -------------------------------------------------------------------


@router.get("/trash", response_model=TrashOut, tags=["trash"])
async def list_trash(trash: Trash, config: Config) -> TrashOut:
    return await trash.list(config.platform.trash)
