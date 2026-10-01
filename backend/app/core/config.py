"""Typed loading of the tunable configuration in ``config/*.yaml``.

Every number an algorithm depends on is declared here with its valid range, so
a bad edit to a YAML file fails at startup with a precise message rather than
silently skewing the learning engine or the AI budget.

Sections are added in the phase that first uses them; unknown keys are
rejected so typos cannot go unnoticed.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.settings import get_settings

Fraction = Annotated[float, Field(ge=0.0, le=1.0)]
Positive = Annotated[float, Field(gt=0.0)]
NonNegative = Annotated[float, Field(ge=0.0)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- learning.yaml -----------------------------------------------------------


class DifficultyWeights(_Strict):
    easy: Positive
    medium: Positive
    hard: Positive
    exam: Positive

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.easy <= self.medium <= self.hard <= self.exam:
            raise ValueError("difficulty weights must not decrease from easy to exam")
        return self


class MasteryConfig(_Strict):
    half_life_days: Positive
    prior_accuracy: Fraction
    prior_weight: Positive
    flashcard_blend_lambda: Fraction
    low_data_weight_threshold: Positive
    low_confidence_mark_weight: Fraction
    difficulty_weights: DifficultyWeights


class TargetSuccess(_Strict):
    min: Fraction
    max: Fraction

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.min >= self.max:
            raise ValueError("target_success.min must be below target_success.max")
        return self


class DifficultyConfig(_Strict):
    target_success: TargetSuccess


class SpacedRepetitionConfig(_Strict):
    target_retention: Annotated[float, Field(gt=0.0, lt=1.0)]
    exam_final_window_days: Annotated[int, Field(ge=1)]


class MistakesConfig(_Strict):
    recurring_min_count: Annotated[int, Field(ge=2)]
    recurring_window_days: Annotated[int, Field(ge=1)]
    categories: Annotated[tuple[str, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _unique(self) -> Self:
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("mistake categories must be unique")
        return self


class LearningConfig(_Strict):
    mastery: MasteryConfig
    difficulty: DifficultyConfig
    spaced_repetition: SpacedRepetitionConfig
    mistakes: MistakesConfig


# --- ai.yaml -----------------------------------------------------------------


class ModelPricing(_Strict):
    """USD per million tokens."""

    input: NonNegative
    output: NonNegative
    cache_write: NonNegative
    cache_read: NonNegative


Effort = Literal["low", "medium", "high", "xhigh", "max"]


class ModelSpec(_Strict):
    id: Annotated[str, Field(min_length=1)]
    context_window: Annotated[int, Field(gt=0)]
    pricing: ModelPricing
    # Effort levels the API accepts for this model; empty if it takes none.
    effort_levels: tuple[Effort, ...] = ()


class Step(_Strict):
    """One model call: which model, at which effort (ADR 0006)."""

    model: str
    effort: Effort | None = None


class Route(Step):
    escalate_to: Step | None = None

    def steps(self) -> tuple[Step, ...]:
        base = Step(model=self.model, effort=self.effort)
        return (base,) if self.escalate_to is None else (base, self.escalate_to)


class BudgetConfig(_Strict):
    """Spending caps in the user's currency. The API bills in USD, so costs
    are converted with `usd_to_currency` before comparing against the caps."""

    currency: Literal["GBP", "USD", "EUR"]
    usd_to_currency: Positive
    daily_cap: Positive
    monthly_cap: Positive
    warn_fraction: Annotated[float, Field(gt=0.0, lt=1.0)]
    confirm_above_tokens: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.daily_cap > self.monthly_cap:
            raise ValueError("daily_cap cannot exceed monthly_cap")
        if self.currency == "USD" and self.usd_to_currency != 1:
            raise ValueError("usd_to_currency must be 1 when currency is USD")
        return self

    def from_usd(self, usd: float) -> float:
        return usd * self.usd_to_currency


class AIConfig(_Strict):
    models: dict[str, ModelSpec]
    routing: dict[str, Route]
    budget: BudgetConfig

    @model_validator(mode="after")
    def _routes_are_valid(self) -> Self:
        for task, route in self.routing.items():
            steps = route.steps()
            for step in steps:
                spec = self.models.get(step.model)
                if spec is None:
                    raise ValueError(
                        f"routing.{task} references unknown model alias '{step.model}'"
                    )
                # Effort is explicit wherever it exists, so a change in an API
                # default can never silently change behaviour or cost.
                if spec.effort_levels and step.effort is None:
                    raise ValueError(f"routing.{task}: model '{step.model}' needs an effort")
                if not spec.effort_levels and step.effort is not None:
                    raise ValueError(
                        f"routing.{task}: model '{step.model}' does not accept an effort"
                    )
                if step.effort is not None and step.effort not in spec.effort_levels:
                    raise ValueError(
                        f"routing.{task}: effort '{step.effort}' not available on '{step.model}'"
                    )
            if len(steps) == 2 and steps[0] == steps[1]:
                raise ValueError(f"routing.{task}: escalation must differ from the first step")
        return self


# --- platform.yaml -----------------------------------------------------------

PositiveInt = Annotated[int, Field(gt=0)]


class AuthConfig(_Strict):
    session_idle_hours: PositiveInt
    session_absolute_days: PositiveInt
    session_touch_interval_seconds: PositiveInt
    password_min_length: Annotated[int, Field(ge=8)]
    password_max_length: PositiveInt

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.session_idle_hours > self.session_absolute_days * 24:
            raise ValueError("session_idle_hours cannot exceed session_absolute_days")
        if self.password_min_length > self.password_max_length:
            raise ValueError("password_min_length cannot exceed password_max_length")
        return self


class RateLimit(_Strict):
    max_attempts: PositiveInt
    window_seconds: PositiveInt


class RateLimitsConfig(_Strict):
    login: RateLimit


class TrashConfig(_Strict):
    retention_days: PositiveInt


class PlatformConfig(_Strict):
    auth: AuthConfig
    rate_limits: RateLimitsConfig
    trash: TrashConfig


# --- loading -----------------------------------------------------------------


class AppConfig(_Strict):
    learning: LearningConfig
    ai: AIConfig
    platform: PlatformConfig


class ConfigError(RuntimeError):
    """Raised when a config file is missing or invalid."""


def _load_yaml[T: BaseModel](path: Path, model: type[T]) -> T:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name} is not valid YAML: {exc}") from exc
    try:
        return model.model_validate(raw)
    except ValueError as exc:
        raise ConfigError(f"{path.name} failed validation:\n{exc}") from exc


def load_config(config_dir: Path) -> AppConfig:
    return AppConfig(
        learning=_load_yaml(config_dir / "learning.yaml", LearningConfig),
        ai=_load_yaml(config_dir / "ai.yaml", AIConfig),
        platform=_load_yaml(config_dir / "platform.yaml", PlatformConfig),
    )


@lru_cache
def get_config() -> AppConfig:
    return load_config(get_settings().config_dir)
