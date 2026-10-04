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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.settings import get_settings

Fraction = Annotated[float, Field(ge=0.0, le=1.0)]
Positive = Annotated[float, Field(gt=0.0)]
NonNegative = Annotated[float, Field(ge=0.0)]
PositiveInt = Annotated[int, Field(gt=0)]


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


class InitialRatings(_Strict):
    easy: Positive
    medium: Positive
    hard: Positive
    exam: Positive


class DifficultyConfig(_Strict):
    initial_ratings: InitialRatings
    target_success: TargetSuccess
    initial_ability: Positive
    k_ability: Positive
    k_question: Positive


class SpacedRepetitionConfig(_Strict):
    target_retention: Annotated[float, Field(gt=0.0, lt=1.0)]
    exam_final_window_days: Annotated[int, Field(ge=1)]
    learning_steps_minutes: tuple[Positive, ...]
    relearning_steps_minutes: tuple[Positive, ...]
    maximum_interval_days: PositiveInt
    fuzz: bool
    new_cards_per_day: PositiveInt


class PriorityWeights(_Strict):
    weakness: NonNegative
    overdue: NonNegative
    urgency: NonNegative
    recurring: NonNegative
    gap: NonNegative


class TopUpConfig(_Strict):
    enabled: bool
    min_questions_per_topic: PositiveInt
    generate: PositiveInt
    max_topics_per_day: Annotated[int, Field(ge=0)]


class DailyQuizConfig(_Strict):
    weights: PriorityWeights
    overdue_after_days: Positive
    coverage_attempts: PositiveInt
    default_minutes: PositiveInt
    default_seconds_per_question: PositiveInt
    min_questions: PositiveInt
    max_questions: PositiveInt
    module_floor: Annotated[int, Field(ge=0)]
    recurring_targets: Annotated[int, Field(ge=0)]
    avoid_repeat_days: NonNegative
    top_up: TopUpConfig

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.min_questions > self.max_questions:
            raise ValueError("min_questions cannot exceed max_questions")
        return self


class ProfileConfig(_Strict):
    refresh_days: PositiveInt
    recent_errors: PositiveInt
    # A snapshot (and Claude's summary) needs at least this many answers.
    min_answers: PositiveInt


class MistakesConfig(_Strict):
    recurring_min_count: Annotated[int, Field(ge=2)]
    recurring_window_days: Annotated[int, Field(ge=1)]
    description_similarity: Annotated[float, Field(gt=0.0, le=1.0)]
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
    daily_quiz: DailyQuizConfig
    profile: ProfileConfig


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
    # Opt into the API's server-side fallback on safety-classifier refusals.
    server_fallback: bool = False


class Step(_Strict):
    """One model call: which model, at which effort (ADR 0006)."""

    model: str
    effort: Effort | None = None


class Route(Step):
    escalate_to: Step | None = None
    max_tokens: Annotated[int, Field(gt=0, le=128_000)] | None = None

    def steps(self) -> tuple[Step, ...]:
        base = Step(model=self.model, effort=self.effort)
        return (base,) if self.escalate_to is None else (base, self.escalate_to)


class BudgetConfig(_Strict):
    """Spending caps in the user's currency. The API bills in USD, so costs
    are converted with `usd_to_currency` before comparing against the caps."""

    timezone: str
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
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone: {self.timezone}") from exc
        return self

    def from_usd(self, usd: float) -> float:
        return usd * self.usd_to_currency


class ChatConfig(_Strict):
    """The assistant's agent loop and its limits (ARCHITECTURE.md section 9)."""

    # API calls per answer: the first, plus one after each round of tool use.
    max_model_calls: Annotated[int, Field(ge=1, le=10)]
    # Earlier messages resent as context; older ones are dropped.
    history_messages: PositiveInt
    max_message_chars: PositiveInt
    # Characters of a page returned by the read_page tool.
    page_read_max_chars: PositiveInt
    pending_action_minutes: PositiveInt
    # Characters of cited text kept with each stored citation.
    cited_text_max_chars: PositiveInt
    # One answer at a time per conversation; the lock lapses after this long
    # in case an answer never finishes.
    answer_lock_seconds: PositiveInt


class UsageDashboardConfig(_Strict):
    default_days: PositiveInt
    max_days: PositiveInt


class AIConfig(_Strict):
    models: dict[str, ModelSpec]
    default_max_tokens: Annotated[int, Field(gt=0, le=128_000)]
    routing: dict[str, Route]
    budget: BudgetConfig
    chat: ChatConfig
    usage_dashboard: UsageDashboardConfig

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


class UploadSizes(_Strict):
    pdf: PositiveInt
    office: PositiveInt
    image: PositiveInt
    text: PositiveInt


class UploadsConfig(_Strict):
    max_megabytes: UploadSizes
    max_image_pixels: PositiveInt
    zip_max_entries: PositiveInt
    zip_max_uncompressed_megabytes: PositiveInt
    zip_max_compression_ratio: PositiveInt
    max_pdf_pages: PositiveInt

    @property
    def largest_upload_bytes(self) -> int:
        sizes = self.max_megabytes
        return max(sizes.pdf, sizes.office, sizes.image, sizes.text) * 1024 * 1024


class DamageSignals(_Strict):
    maths_font: NonNegative
    orphan_lines: NonNegative
    operator_density: NonNegative
    broken_glyphs: NonNegative


class MathsDamageConfig(_Strict):
    threshold: Annotated[float, Field(gt=0.0, le=1.0)]
    weights: DamageSignals
    saturation: DamageSignals

    @model_validator(mode="after")
    def _positive_saturation(self) -> Self:
        if min(self.saturation.model_dump().values()) <= 0:
            raise ValueError("every maths_damage saturation must be greater than 0")
        return self


class IngestionConfig(_Strict):
    maths_damage: MathsDamageConfig
    scanned_page_min_chars: PositiveInt
    vision_render_dpi: Annotated[int, Field(ge=72, le=400)]
    vision_max_long_edge_px: Annotated[int, Field(ge=256, le=8000)]
    preview_dpi: Annotated[int, Field(ge=36, le=300)]
    table_min_fill: Fraction
    sheet_sample_rows: PositiveInt
    job_timeout_seconds: PositiveInt
    progress_poll_seconds: Annotated[float, Field(gt=0.0, le=30.0)]


class PlatformConfig(_Strict):
    auth: AuthConfig
    rate_limits: RateLimitsConfig
    trash: TrashConfig
    uploads: UploadsConfig
    ingestion: IngestionConfig


# --- retrieval.yaml ----------------------------------------------------------


class ChunkingConfig(_Strict):
    chars_per_token: Positive
    target_tokens: PositiveInt
    max_tokens: PositiveInt
    min_tokens: PositiveInt
    overlap_max_tokens: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.min_tokens <= self.target_tokens <= self.max_tokens:
            raise ValueError("chunking needs min_tokens <= target_tokens <= max_tokens")
        if self.overlap_max_tokens >= self.target_tokens:
            raise ValueError("overlap_max_tokens must be below target_tokens")
        return self


class EmbeddingsConfig(_Strict):
    provider: Literal["fastembed"]
    model: Annotated[str, Field(min_length=1)]
    dimensions: PositiveInt
    batch_size: PositiveInt


class RerankConfig(_Strict):
    enabled: bool
    model: Annotated[str, Field(min_length=1)]
    candidates: PositiveInt


class TierWeights(_Strict):
    university: Positive
    own: Positive


class SearchConfig(_Strict):
    keyword_candidates: PositiveInt
    vector_candidates: PositiveInt
    rrf_k: PositiveInt
    keyword_weight: NonNegative
    tier_weights: TierWeights
    results: PositiveInt
    min_vector_similarity: Annotated[float, Field(ge=-1.0, le=1.0)]
    widen_below: Annotated[int, Field(ge=0)]
    rerank: RerankConfig


class RetrievalConfig(_Strict):
    chunking: ChunkingConfig
    embeddings: EmbeddingsConfig
    search: SearchConfig


# --- practice.yaml -----------------------------------------------------------


class GenerationConfig(_Strict):
    default_items: PositiveInt
    max_items: PositiveInt
    passages: PositiveInt
    max_context_chars: PositiveInt
    near_duplicate_similarity: Annotated[float, Field(gt=0.0, le=1.0)]
    repair_rounds: Annotated[int, Field(ge=0, le=3)]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.default_items > self.max_items:
            raise ValueError("default_items cannot exceed max_items")
        return self


class ValidationConfig(_Strict):
    max_stem_chars: PositiveInt
    min_options: Annotated[int, Field(ge=2)]
    max_options: PositiveInt
    max_rubric_points: PositiveInt
    min_model_answer_chars: PositiveInt
    max_expression_chars: PositiveInt

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.min_options > self.max_options:
            raise ValueError("min_options cannot exceed max_options")
        return self


class MarkingConfig(_Strict):
    spot_check_points: PositiveInt
    spot_check_min_points: PositiveInt
    spot_check_tolerance: Positive
    default_relative_tolerance: Positive
    remark_at_or_below: Literal["low", "medium", "high"]
    correct_at: Annotated[float, Field(gt=0.0, le=1.0)]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.spot_check_min_points > self.spot_check_points:
            raise ValueError("spot_check_min_points cannot exceed spot_check_points")
        return self


class QuizzesConfig(_Strict):
    default_questions: PositiveInt
    max_questions: PositiveInt
    mock_default_minutes: PositiveInt
    max_minutes: PositiveInt
    exam_grace_seconds: Annotated[int, Field(ge=0)]
    weak_area_below: Annotated[float, Field(gt=0.0, le=1.0)]


class PracticeConfig(_Strict):
    generation: GenerationConfig
    validation: ValidationConfig
    marking: MarkingConfig
    quizzes: QuizzesConfig


# --- planner.yaml --------------------------------------------------------------


class AllocationConfig(_Strict):
    session_minutes: PositiveInt
    max_sessions_per_day: PositiveInt
    min_block_minutes: PositiveInt
    need_scale_minutes: PositiveInt
    coverage_bonus: NonNegative
    confidence_step: NonNegative
    importance_step: Annotated[float, Field(ge=0, le=0.5)]
    maintenance_minutes: NonNegative
    maintenance_priority: NonNegative
    min_gap_days: Annotated[int, Field(ge=0)]
    final_days: Annotated[int, Field(ge=0)]
    same_module_penalty: Fraction
    urgency_half_days: Positive
    mock_exam_days_before: Annotated[int, Field(ge=1)]
    horizon_days_without_exams: PositiveInt
    max_horizon_days: PositiveInt

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.min_block_minutes > self.session_minutes:
            raise ValueError("min_block_minutes cannot exceed session_minutes")
        return self


class ReserveConfig(_Strict):
    flashcard_seconds: PositiveInt
    flashcard_max_minutes: Annotated[int, Field(ge=0)]
    daily_quiz_fraction: Fraction
    daily_quiz_min_minutes: Annotated[int, Field(ge=0)]
    daily_quiz_max_minutes: Annotated[int, Field(ge=0)]


class AvailabilityConfig(_Strict):
    default_weekday_minutes: Annotated[int, Field(ge=0)]
    default_weekend_minutes: Annotated[int, Field(ge=0)]
    max_minutes_per_day: PositiveInt


class SessionBuilderConfig(_Strict):
    flashcard_share: Fraction
    mistake_drill_minutes: PositiveInt
    split_above_minutes: PositiveInt
    min_minutes: PositiveInt
    max_minutes: PositiveInt


class NotificationsConfig(_Strict):
    quiz_reminder_hour: Annotated[int, Field(ge=0, le=23)]
    exam_days: tuple[PositiveInt, ...]
    neglected_days: PositiveInt
    flashcards_due_threshold: PositiveInt
    keep_days: PositiveInt


class PlannerConfig(_Strict):
    allocation: AllocationConfig
    reserve: ReserveConfig
    availability: AvailabilityConfig
    session_builder: SessionBuilderConfig
    notifications: NotificationsConfig


# --- loading -----------------------------------------------------------------


class AppConfig(_Strict):
    learning: LearningConfig
    ai: AIConfig
    platform: PlatformConfig
    retrieval: RetrievalConfig
    practice: PracticeConfig
    planner: PlannerConfig


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
        retrieval=_load_yaml(config_dir / "retrieval.yaml", RetrievalConfig),
        practice=_load_yaml(config_dir / "practice.yaml", PracticeConfig),
        planner=_load_yaml(config_dir / "planner.yaml", PlannerConfig),
    )


@lru_cache
def get_config() -> AppConfig:
    return load_config(get_settings().config_dir)
