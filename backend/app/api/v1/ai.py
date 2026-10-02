"""AI spending: the budget status and the usage dashboard."""

from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.ai.budget import BudgetGuard
from app.api.deps import Config, CurrentUser, DbSession
from app.core.errors import AppError
from app.schemas.chat import UsageOut
from app.schemas.documents import BudgetOut
from app.services.usage import UsageService

router = APIRouter(tags=["ai"])


@router.get("/ai/budget", response_model=BudgetOut)
async def ai_budget(
    request: Request, db: DbSession, user: CurrentUser, config: Config
) -> BudgetOut:
    status_ = await BudgetGuard(db, user.id, config.ai.budget).status()
    return BudgetOut(
        currency=status_.currency,
        spent_today=round(status_.spent_today, 4),
        spent_this_month=round(status_.spent_this_month, 4),
        daily_cap=status_.daily_cap,
        monthly_cap=status_.monthly_cap,
        warning=status_.warning,
        exhausted=status_.exhausted,
        configured=request.app.state.claude.available,
    )


@router.get("/ai/usage", response_model=UsageOut)
async def ai_usage(
    db: DbSession,
    user: CurrentUser,
    config: Config,
    days: Annotated[int | None, Query(ge=1)] = None,
) -> UsageOut:
    """Requests, tokens and estimated cost over the last `days` days."""
    limits = config.ai.usage_dashboard
    days = days or limits.default_days
    if days > limits.max_days:
        raise AppError("range_too_long", f"Choose at most {limits.max_days} days.", 422)
    return await UsageService(db, user.id, config.ai).report(days)
