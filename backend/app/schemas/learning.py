import uuid
from datetime import date, datetime
from typing import Any

from pydantic import Field

from app.schemas.common import Input, Output
from app.schemas.practice import FlashcardOut


class TopicProgress(Output):
    """A topic's estimated strength with its evidence, e.g.
    "est. 72% · 14 attempts · last practised 6 days ago"."""

    topic_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    title: str
    strength: float
    accuracy: float
    retrievability: float | None
    attempts: int
    weight: float
    low_data: bool
    last_practised_at: datetime | None
    # Including subtopics, weighted by their evidence.
    subtree_strength: float
    subtree_attempts: int


class WeakTopic(Output):
    module_id: uuid.UUID
    module_code: str
    topic_id: uuid.UUID | None
    title: str
    strength: float
    attempts: int
    low_data: bool
    last_practised_at: datetime | None


class DueCard(FlashcardOut):
    # Days until due again after each rating (1 Again ... 4 Easy).
    intervals: dict[int, float]


class DueCards(Output):
    cards: list[DueCard]
    counts: dict[str, int]


class ReviewIn(Input):
    rating: int = Field(ge=1, le=4)
    duration_ms: int | None = Field(default=None, ge=0, le=3_600_000)


class PlanBucket(Output):
    module_id: uuid.UUID
    module_code: str
    topic_id: uuid.UUID | None
    title: str
    strength: float
    attempts: int
    low_data: bool
    priority: float
    terms: dict[str, float]
    available: int
    allocated: int
    reasons: list[str]


class DailyPlanOut(Output):
    minutes: int
    seconds_per_question: float
    questions: int
    buckets: list[PlanBucket]


class DailyStart(Input):
    minutes: int | None = Field(default=None, ge=5, le=240)


class DailyStarted(Output):
    attempt_id: uuid.UUID
    plan: DailyPlanOut


class MistakePattern(Output):
    description: str
    count: int


class MistakeExample(Output):
    answer_id: uuid.UUID
    attempt_id: uuid.UUID
    question_id: uuid.UUID
    stem_md: str
    at: datetime
    description: str


class MistakeGroupOut(Output):
    module_id: uuid.UUID
    module_code: str
    topic_id: uuid.UUID | None
    topic_title: str
    category: str
    label: str
    count: int
    recent: int
    recurring: bool
    last_at: datetime | None
    patterns: list[MistakePattern]
    examples: list[MistakeExample]


class ProfileSnapshotOut(Output):
    week_start: date
    metrics: dict[str, Any]
    summary_md: str | None
    computed_at: datetime


class ProfileOut(Output):
    current: dict[str, Any]
    snapshot: ProfileSnapshotOut | None
