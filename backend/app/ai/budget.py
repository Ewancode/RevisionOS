"""Spending caps and cost estimates (ARCHITECTURE.md section 8, BudgetGuard).

Every call is checked against the daily and monthly caps *before* it is
made, using its worst-case cost (all input tokens plus the full output
allowance), so the caps cannot be overshot by one large request.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import AIConfig, BudgetConfig, ModelPricing
from app.core.errors import AppError
from app.models import AIUsage

PER_MILLION = 1_000_000


@dataclass(frozen=True)
class TokenCounts:
    input: int
    output: int
    cache_write: int = 0
    cache_read: int = 0


def cost_usd(pricing: ModelPricing, tokens: TokenCounts) -> float:
    return (
        tokens.input * pricing.input
        + tokens.output * pricing.output
        + tokens.cache_write * pricing.cache_write
        + tokens.cache_read * pricing.cache_read
    ) / PER_MILLION


def pricing_for(model_id: str, config: AIConfig) -> ModelPricing:
    """Price by the model that actually answered. An unknown id (e.g. a
    server-side fallback model not in our catalogue) is priced as the most
    expensive configured model, so estimates err on the high side."""
    for spec in config.models.values():
        if spec.id == model_id:
            return spec.pricing
    return max((s.pricing for s in config.models.values()), key=lambda p: p.output)


@dataclass(frozen=True)
class BudgetStatus:
    currency: str
    spent_today: float
    spent_this_month: float
    daily_cap: float
    monthly_cap: float
    warn_fraction: float

    @property
    def warning(self) -> bool:
        return (
            self.spent_today >= self.daily_cap * self.warn_fraction
            or self.spent_this_month >= self.monthly_cap * self.warn_fraction
        )

    @property
    def exhausted(self) -> bool:
        return self.spent_today >= self.daily_cap or self.spent_this_month >= self.monthly_cap


def budget_exceeded(status: BudgetStatus) -> AppError:
    which = "daily" if status.spent_today >= status.daily_cap else "monthly"
    return AppError(
        "ai_budget_reached",
        f"Your {which} AI budget is used up. AI features resume when it resets, "
        "or raise the cap in config/ai.yaml.",
        429,
    )


class BudgetGuard:
    def __init__(self, db: AsyncSession, user_id: uuid.UUID, config: BudgetConfig) -> None:
        self.db = db
        self.user_id = user_id
        self.config = config

    def _period_starts(self, now: datetime) -> tuple[datetime, datetime]:
        local = now.astimezone(ZoneInfo(self.config.timezone))
        day = datetime.combine(local.date(), time.min, tzinfo=local.tzinfo)
        month = day.replace(day=1)
        return day, month

    async def _spent_usd_since(self, start: datetime) -> float:
        total = await self.db.scalar(
            select(func.coalesce(func.sum(AIUsage.estimated_cost_usd), 0.0)).where(
                AIUsage.user_id == self.user_id, AIUsage.created_at >= start
            )
        )
        return float(total or 0.0)

    async def status(self) -> BudgetStatus:
        day, month = self._period_starts(utcnow())
        c = self.config
        return BudgetStatus(
            currency=c.currency,
            spent_today=c.from_usd(await self._spent_usd_since(day)),
            spent_this_month=c.from_usd(await self._spent_usd_since(month)),
            daily_cap=c.daily_cap,
            monthly_cap=c.monthly_cap,
            warn_fraction=c.warn_fraction,
        )

    async def ensure_can_spend(self, worst_case_usd: float) -> BudgetStatus:
        status = await self.status()
        extra = self.config.from_usd(worst_case_usd)
        if (
            status.spent_today + extra > status.daily_cap
            or status.spent_this_month + extra > status.monthly_cap
        ):
            raise budget_exceeded(status)
        return status
