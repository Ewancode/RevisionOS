"""Liveness and readiness probes. Unauthenticated by design; they reveal
nothing beyond whether each dependency answers."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 2.0

Check = Callable[[], Awaitable[None]]
CheckStatus = Literal["ok", "unavailable"]


class LivenessResponse(BaseModel):
    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, CheckStatus]


def get_readiness_checks(request: Request) -> dict[str, Check]:
    engine: AsyncEngine = request.app.state.engine
    redis: Redis = request.app.state.redis

    async def database() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def cache() -> None:
        await redis.ping()

    return {"database": database, "redis": cache}


@router.get("", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    return LivenessResponse(status="ok")


async def _run(name: str, check: Check) -> CheckStatus:
    try:
        await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("readiness check failed", extra={"check": name}, exc_info=True)
        return "unavailable"
    return "ok"


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
async def readiness(
    response: Response,
    checks: dict[str, Check] = Depends(get_readiness_checks),  # noqa: B008
) -> ReadinessResponse:
    names = list(checks)
    results = await asyncio.gather(*(_run(n, checks[n]) for n in names))
    statuses = dict(zip(names, results, strict=True))
    ready = all(s == "ok" for s in statuses.values())
    if not ready:
        response.status_code = 503
    return ReadinessResponse(status="ready" if ready else "not_ready", checks=statuses)
