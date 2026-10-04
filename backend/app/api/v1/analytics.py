"""Analytics: dashboards, trends and exam readiness. Every number comes with
the stored data it was computed from; no AI is involved."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import Client, Config, CurrentUser, DbSession
from app.schemas.analytics import ModuleAnalyticsOut, OverviewOut, ReadinessOut, TrendsOut
from app.services.analytics import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _analytics(
    db: DbSession, user: CurrentUser, client: Client, config: Config
) -> AnalyticsService:
    return AnalyticsService(db, user.id, client, config=config)


Analytics = Annotated[AnalyticsService, Depends(_analytics)]


@router.get("/overview", response_model=OverviewOut)
async def overview(analytics: Analytics) -> OverviewOut:
    """The main dashboard: today, streak, this week, modules, topics, recent items."""
    return await analytics.overview()


@router.get("/trends", response_model=TrendsOut)
async def trends(analytics: Analytics, module_id: uuid.UUID | None = None) -> TrendsOut:
    """Weekly accuracy, study time, mistakes and consistency, and daily activity."""
    return await analytics.trends(module_id)


@router.get("/readiness", response_model=list[ReadinessOut])
async def readiness(analytics: Analytics) -> list[ReadinessOut]:
    """For each upcoming exam: a summary of preparation so far, not a predicted mark."""
    return await analytics.readiness()


@router.get("/modules/{module_id}", response_model=ModuleAnalyticsOut)
async def module(module_id: uuid.UUID, analytics: Analytics) -> ModuleAnalyticsOut:
    """A module's dashboard figures."""
    return await analytics.module(module_id)
