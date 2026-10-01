"""The single gateway to the Claude API (ARCHITECTURE.md section 8).

Every call: resolve the route (model + effort) from config, check the
budget against the call's worst-case cost, call the API, then record the
interaction and its token usage. Nothing else in the app talks to Anthropic.
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol, cast

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.budget import BudgetGuard, TokenCounts, cost_usd, pricing_for
from app.core.config import AIConfig, ModelSpec, Step
from app.core.errors import AppError
from app.models import AIInteraction, AIUsage

logger = logging.getLogger(__name__)

SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Rough tokens-per-character for budgeting text we have not counted exactly.
CHARS_PER_TOKEN = 3.5


class MessagesAPI(Protocol):
    async def create(self, **kwargs: Any) -> Any: ...


class BetaAPI(Protocol):
    @property
    def messages(self) -> MessagesAPI: ...


class AnthropicLike(Protocol):
    """The slice of `anthropic.AsyncAnthropic` used here (tests pass a fake)."""

    @property
    def messages(self) -> MessagesAPI: ...

    @property
    def beta(self) -> BetaAPI: ...


@dataclass(frozen=True)
class AIResult:
    text: str
    served_model: str
    interaction_id: uuid.UUID
    tokens: TokenCounts


def ai_unavailable(code: str, message: str) -> AppError:
    return AppError(code, message, 503)


def image_tokens(width: int, height: int) -> int:
    """Anthropic's published estimate for image input: width x height / 750."""
    return (width * height) // 750 + 1


def text_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


class ClaudeClient:
    def __init__(self, sdk: AnthropicLike | None, config: AIConfig) -> None:
        # sdk is None when no API key is configured: AI features then fail
        # with a clear error instead of crashing the app.
        self.sdk = sdk
        self.config = config

    @property
    def available(self) -> bool:
        return self.sdk is not None

    def _step(self, task: str, escalate: bool) -> tuple[Step, ModelSpec, int]:
        route = self.config.routing[task]
        step: Step = route.escalate_to if escalate and route.escalate_to else route
        max_tokens = route.max_tokens or self.config.default_max_tokens
        return step, self.config.models[step.model], max_tokens

    async def run(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        task: str,
        prompt_version: str,
        system: str,
        content: list[dict[str, Any]],
        estimated_input_tokens: int,
        output_schema: dict[str, Any] | None = None,
        escalate: bool = False,
        document_id: uuid.UUID | None = None,
        module_id: uuid.UUID | None = None,
    ) -> AIResult:
        if self.sdk is None:
            raise ai_unavailable(
                "ai_not_configured", "Claude is not configured: set ANTHROPIC_API_KEY in .env."
            )
        step, spec, max_tokens = self._step(task, escalate)
        worst_case = cost_usd(spec.pricing, TokenCounts(estimated_input_tokens, max_tokens))
        guard = BudgetGuard(db, user_id, self.config.budget)
        try:
            await guard.ensure_can_spend(worst_case)
        except AppError:
            self._record(
                db, user_id, task, spec, step, prompt_version, "budget_blocked", document_id
            )
            await db.commit()
            raise

        output_config: dict[str, Any] = {}
        if step.effort:
            output_config["effort"] = step.effort
        if output_schema:
            output_config["format"] = {"type": "json_schema", "schema": output_schema}
        request: dict[str, Any] = {
            "model": spec.id,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": content}],
        }
        if output_config:
            request["output_config"] = output_config

        started = time.perf_counter()
        try:
            if spec.server_fallback:
                response = await self.sdk.beta.messages.create(
                    betas=[SERVER_FALLBACK_BETA], fallbacks="default", **request
                )
            else:
                response = await self.sdk.messages.create(**request)
        except anthropic.APIError as exc:
            code = type(exc).__name__
            logger.warning("claude call failed", extra={"task": task, "error": code})
            self._record(
                db, user_id, task, spec, step, prompt_version, "error", document_id, error_code=code
            )
            await db.commit()
            raise ai_unavailable(
                "ai_unavailable", "Claude could not be reached. Try again shortly."
            ) from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        served = str(getattr(response, "model", spec.id))
        usage = response.usage
        tokens = TokenCounts(
            input=int(usage.input_tokens or 0),
            output=int(usage.output_tokens or 0),
            cache_write=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
            cache_read=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        )
        stop_reason = getattr(response, "stop_reason", None)
        status = "refused" if stop_reason == "refusal" else "ok"
        if stop_reason == "max_tokens":
            status = "error"
        interaction = self._record(
            db,
            user_id,
            task,
            spec,
            step,
            prompt_version,
            status,
            document_id,
            served_model=served,
            stop_reason=stop_reason,
            latency_ms=latency_ms,
            request_id=getattr(response, "_request_id", None),
            error_code="max_tokens" if stop_reason == "max_tokens" else None,
        )
        # Usage is recorded whatever the outcome: refused and truncated calls are billed.
        db.add(
            AIUsage(
                user_id=user_id,
                interaction_id=interaction.id,
                feature=task,
                model=served,
                module_id=module_id,
                input_tokens=tokens.input,
                output_tokens=tokens.output,
                cache_write_tokens=tokens.cache_write,
                cache_read_tokens=tokens.cache_read,
                estimated_cost_usd=cost_usd(pricing_for(served, self.config), tokens),
            )
        )
        await db.commit()

        if stop_reason == "refusal":
            raise AppError("ai_refused", "Claude declined this request.", 422)
        if stop_reason == "max_tokens":
            raise AppError("ai_truncated", "Claude's answer was cut off (output limit).", 502)
        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
        return AIResult(text, served, interaction.id, tokens)

    def _record(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        task: str,
        spec: ModelSpec,
        step: Step,
        prompt_version: str,
        status: str,
        document_id: uuid.UUID | None,
        **fields: Any,
    ) -> AIInteraction:
        interaction = AIInteraction(
            id=uuid.uuid4(),
            user_id=user_id,
            feature=task,
            requested_model=spec.id,
            effort=step.effort,
            prompt_version=prompt_version,
            status=status,
            document_id=document_id,
            **fields,
        )
        db.add(interaction)
        return interaction


def parse_json(text: str) -> dict[str, Any]:
    """Structured outputs guarantee valid JSON; anything else is an API fault."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AppError("ai_bad_output", "Claude returned malformed output.", 502) from exc
    if not isinstance(value, dict):
        raise AppError("ai_bad_output", "Claude returned malformed output.", 502)
    return value


def create_client(api_key: str | None, config: AIConfig) -> ClaudeClient:
    if not api_key:
        return ClaudeClient(None, config)
    sdk = anthropic.AsyncAnthropic(api_key=api_key, max_retries=2)
    return ClaudeClient(cast(AnthropicLike, sdk), config)
