import uuid
from datetime import date, datetime
from typing import Annotated, Any, ClassVar, Literal

from pydantic import AwareDatetime, Field

from app.schemas.common import Input, Output, Patch, Text200

Minutes = Annotated[int, Field(ge=0, le=1440)]
Weekday = Annotated[int, Field(ge=0, le=6)]


class ExamIn(Input):
    module_id: uuid.UUID
    title: Text200
    starts_at: AwareDatetime
    duration_minutes: int = Field(ge=1, le=600)
    location: Text200 | None = None
    weighting: int | None = Field(default=None, ge=1, le=100)
    confidence: int | None = Field(default=None, ge=1, le=5)
    notes: Annotated[str, Field(max_length=2000)] | None = None
    # None or empty: the whole module.
    topic_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)


class ExamUpdate(Patch):
    required_fields: ClassVar[frozenset[str]] = frozenset(
        {"title", "starts_at", "duration_minutes", "topic_ids"}
    )
    title: Text200 | None = None
    starts_at: AwareDatetime | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=600)
    location: Text200 | None = None
    weighting: int | None = Field(default=None, ge=1, le=100)
    confidence: int | None = Field(default=None, ge=1, le=5)
    notes: Annotated[str, Field(max_length=2000)] | None = None
    topic_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)


class ExamOut(Output):
    id: uuid.UUID
    module_id: uuid.UUID
    module_code: str
    title: str
    starts_at: datetime
    duration_minutes: int
    location: str | None
    weighting: int | None
    confidence: int | None
    notes: str | None
    topic_ids: list[uuid.UUID]
    days_until: int


class Override(Input):
    day: date
    minutes: Minutes
    note: Annotated[str, Field(max_length=200)] | None = None


class AvailabilityOut(Output):
    # Minutes per weekday (0 = Monday), with defaults filled in.
    weekdays: list[int]
    # Which weekdays you have set yourself.
    custom: list[bool]
    overrides: list[dict[str, Any]]


class AvailabilityIn(Input):
    # None leaves a weekday as it is.
    weekdays: list[Minutes | None] = Field(min_length=7, max_length=7)
    overrides: list[Override] = Field(default_factory=list, max_length=366)


class AvailabilityText(Input):
    text: Annotated[str, Field(min_length=1, max_length=1000)]


class AvailabilityProposal(Output):
    weekdays: list[int | None]
    dates: list[dict[str, Any]]
    note: str


class PreferencesOut(Output):
    session_minutes: int
    max_sessions_per_day: int
    rest_weekdays: list[int]
    notify_exams: bool
    notify_quiz: bool
    notify_neglected: bool
    notify_flashcards: bool
    quiz_reminder_hour: int
    quiet_from: int | None
    quiet_to: int | None


class PreferencesIn(Patch):
    session_minutes: int | None = Field(default=None, ge=15, le=240)
    max_sessions_per_day: int | None = Field(default=None, ge=1, le=10)
    rest_weekdays: list[Weekday] | None = Field(default=None, max_length=7)
    notify_exams: bool | None = None
    notify_quiz: bool | None = None
    notify_neglected: bool | None = None
    notify_flashcards: bool | None = None
    quiz_reminder_hour: int | None = Field(default=None, ge=0, le=23)
    quiet_from: int | None = Field(default=None, ge=0, le=23)
    quiet_to: int | None = Field(default=None, ge=0, le=23)


class StudySessionOut(Output):
    id: uuid.UUID
    module_id: uuid.UUID
    module_code: str
    topic_id: uuid.UUID | None
    title: str
    exam_id: uuid.UUID | None
    kind: Literal["topic", "mock_exam"]
    day: date
    minutes: int
    status: Literal["planned", "done", "missed", "skipped"]
    locked: bool
    actual_minutes: int | None
    reason: str


class Shortfall(Output):
    exam_id: uuid.UUID
    title: str
    needed_minutes: int
    planned_minutes: int
    available_minutes: int
    left_out: list[str]
    reason: Literal["time", "spacing"]


class PlanOut(Output):
    generated_at: datetime
    starts: date
    ends: date
    shortfalls: list[Shortfall]
    today: list[StudySessionOut]
    upcoming: list[StudySessionOut]
    exams: list[ExamOut]


class SessionMove(Input):
    day: date
    minutes: int | None = Field(default=None, ge=5, le=480)


class SessionStatusIn(Input):
    status: Literal["done", "skipped", "missed", "planned"]
    actual_minutes: int | None = Field(default=None, ge=1, le=1440)


class CalendarDay(Output):
    day: date
    available_minutes: int
    sessions: list[StudySessionOut]
    exams: list[ExamOut]
    quizzes: list[dict[str, Any]]
    reviews: int
    due_cards: int


class CalendarOut(Output):
    start: date
    end: date
    days: list[CalendarDay]


class BuiltBlock(Output):
    kind: Literal["flashcards", "mistake_drill", "topic"]
    title: str
    minutes: int
    reason: str
    action: dict[str, Any]


class BuiltSession(Output):
    minutes: int
    summary: str
    blocks: list[BuiltBlock]


class NotificationOut(Output):
    id: int
    kind: str
    title: str
    body: str
    link: str | None
    read_at: datetime | None
    created_at: datetime


class PushConfig(Output):
    # Push is off until the server has VAPID keys (make vapid-keys).
    enabled: bool
    public_key: str | None
    devices: int


class PushKeys(Input):
    p256dh: Annotated[str, Field(min_length=1, max_length=200)]
    auth: Annotated[str, Field(min_length=1, max_length=100)]


class PushSubscriptionIn(Input):
    endpoint: Annotated[str, Field(pattern=r"^https://", max_length=2000)]
    keys: PushKeys
    label: Annotated[str, Field(max_length=100)] | None = None


class PushUnsubscribe(Input):
    endpoint: Annotated[str, Field(max_length=2000)]


class PushTestOut(Output):
    delivered: int


class NotificationsOut(Output):
    unread: int
    items: list[NotificationOut]
