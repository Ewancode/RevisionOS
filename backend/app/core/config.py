"""Typed loading of the tunable configuration in ``config/*.yaml``.

Every number an algorithm depends on is declared here with its valid range, so
a bad edit to a YAML file fails at startup with a precise message rather than
silently skewing the learning engine or the AI budget.

Sections are added in the phase that first uses them; unknown keys are
rejected so typos cannot go unnoticed.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Self

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


class ModelSpec(_Strict):
    id: Annotated[str, Field(min_length=1)]
    context_window: Annotated[int, Field(gt=0)]
    pricing: ModelPricing


class Route(_Strict):
    model: str
    escalate_to: str | None = None


class BudgetConfig(_Strict):
    daily_usd_cap: Positive
    monthly_usd_cap: Positive
    warn_fraction: Annotated[float, Field(gt=0.0, lt=1.0)]
    confirm_above_tokens: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def _daily_within_monthly(self) -> Self:
        if self.daily_usd_cap > self.monthly_usd_cap:
            raise ValueError("daily_usd_cap cannot exceed monthly_usd_cap")
        return self


class AIConfig(_Strict):
    models: dict[str, ModelSpec]
    routing: dict[str, Route]
    budget: BudgetConfig

    @model_validator(mode="after")
    def _routes_reference_known_models(self) -> Self:
        for task, route in self.routing.items():
            for alias in (route.model, route.escalate_to):
                if alias is not None and alias not in self.models:
                    raise ValueError(f"routing.{task} references unknown model alias '{alias}'")
        return self


# --- loading -----------------------------------------------------------------


class AppConfig(_Strict):
    learning: LearningConfig
    ai: AIConfig


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
    )


@lru_cache
def get_config() -> AppConfig:
    return load_config(get_settings().config_dir)
