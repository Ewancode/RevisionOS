"""The AI usage dashboard (SPEC section 45): requests, tokens and estimated
cost by feature, model, module and day. Pure queries over `ai_usage`."""

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import AIConfig
from app.models import AIInteraction, AIUsage, Module
from app.schemas.chat import UsageBreakdown, UsageDay, UsageOut, UsageTotals

FEATURE_LABELS = {
    "chat": "Assistant",
    "maths_transcription": "Maths transcription",
}


def _label(feature: str) -> str:
    return FEATURE_LABELS.get(feature, feature.replace("_", " ").capitalize())


class UsageService:
    def __init__(self, db: AsyncSession, user_id: uuid.UUID, config: AIConfig) -> None:
        self.db = db
        self.user_id = user_id
        self.config = config
        self.zone = ZoneInfo(config.budget.timezone)

    def _money(self, usd: float | None) -> float:
        return round(self.config.budget.from_usd(float(usd or 0.0)), 4)

    def _model_label(self, model_id: str) -> str:
        for alias, spec in self.config.models.items():
            if spec.id == model_id:
                return alias.capitalize()
        return model_id

    async def _grouped(
        self, key: Any, since: datetime, *joins: Any
    ) -> list[tuple[Any, int, int, float]]:
        stmt = select(
            key,
            func.count(AIUsage.id),
            func.coalesce(func.sum(AIUsage.input_tokens + AIUsage.output_tokens), 0),
            func.coalesce(func.sum(AIUsage.estimated_cost_usd), 0.0),
        ).where(AIUsage.user_id == self.user_id, AIUsage.created_at >= since)
        for target, on in joins:
            stmt = stmt.outerjoin(target, on)
        rows = await self.db.execute(
            stmt.group_by(key).order_by(func.sum(AIUsage.estimated_cost_usd).desc())
        )
        return [(r[0], int(r[1]), int(r[2]), float(r[3])) for r in rows.all()]

    async def report(self, days: int) -> UsageOut:
        today = utcnow().astimezone(self.zone).date()
        first = today - timedelta(days=days - 1)
        since = datetime.combine(first, time.min, tzinfo=self.zone)

        totals = (
            await self.db.execute(
                select(
                    func.count(AIUsage.id),
                    func.coalesce(func.sum(AIUsage.input_tokens), 0),
                    func.coalesce(func.sum(AIUsage.output_tokens), 0),
                    func.coalesce(func.sum(AIUsage.cache_read_tokens), 0),
                    func.coalesce(func.sum(AIUsage.cache_write_tokens), 0),
                    func.coalesce(func.sum(AIUsage.estimated_cost_usd), 0.0),
                ).where(AIUsage.user_id == self.user_id, AIUsage.created_at >= since)
            )
        ).one()
        blocked = await self.db.scalar(
            select(func.count(AIInteraction.id)).where(
                AIInteraction.user_id == self.user_id,
                AIInteraction.created_at >= since,
                AIInteraction.status == "budget_blocked",
            )
        )

        by_feature = [
            UsageBreakdown(key=k, label=_label(k), requests=n, tokens=t, cost=self._money(c))
            for k, n, t, c in await self._grouped(AIUsage.feature, since)
        ]
        by_model = [
            UsageBreakdown(
                key=k, label=self._model_label(k), requests=n, tokens=t, cost=self._money(c)
            )
            for k, n, t, c in await self._grouped(AIUsage.model, since)
        ]
        by_module = [
            UsageBreakdown(
                key=k or "none",
                label=k or "Not tied to a module",
                requests=n,
                tokens=t,
                cost=self._money(c),
            )
            for k, n, t, c in await self._grouped(
                Module.code, since, (Module, Module.id == AIUsage.module_id)
            )
        ]

        local_day = func.date(func.timezone(self.config.budget.timezone, AIUsage.created_at))
        day_rows = (
            await self.db.execute(
                select(
                    local_day,
                    func.count(AIUsage.id),
                    func.coalesce(func.sum(AIUsage.estimated_cost_usd), 0.0),
                )
                .where(AIUsage.user_id == self.user_id, AIUsage.created_at >= since)
                .group_by(local_day)
            )
        ).all()
        per_day: dict[date, tuple[int, float]] = {r[0]: (int(r[1]), float(r[2])) for r in day_rows}
        # Every day in the range, so the chart has no gaps.
        by_day = [
            UsageDay(
                day=d,
                requests=per_day.get(d, (0, 0.0))[0],
                cost=self._money(per_day.get(d, (0, 0.0))[1]),
            )
            for d in (first + timedelta(days=i) for i in range(days))
        ]

        return UsageOut(
            currency=self.config.budget.currency,
            days=days,
            since=first,
            totals=UsageTotals(
                requests=int(totals[0]),
                blocked_requests=int(blocked or 0),
                input_tokens=int(totals[1]),
                output_tokens=int(totals[2]),
                cache_read_tokens=int(totals[3]),
                cache_write_tokens=int(totals[4]),
                cost=self._money(totals[5]),
            ),
            by_feature=by_feature,
            by_model=by_model,
            by_module=by_module,
            by_day=by_day,
        )
