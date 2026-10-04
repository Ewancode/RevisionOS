import uuid
from datetime import date, datetime

from app.schemas.common import Output
from app.schemas.planner import BuiltBlock


class MetricOut(Output):
    """A number and the stored data it was computed from."""

    value: float | None
    basis: str


class SummaryOut(Output):
    days: int
    answered: MetricOut
    correct: MetricOut
    accuracy: MetricOut
    study_minutes: MetricOut
    reviews: MetricOut
    mistakes: MetricOut


class TodayOut(Output):
    progress: MetricOut
    planned_minutes: int
    done_minutes: int


class StreakOut(Output):
    current: MetricOut
    longest: MetricOut


class TopicStat(Output):
    module_id: uuid.UUID
    module_code: str
    topic_id: uuid.UUID | None
    title: str
    strength: float
    attempts: int


class ModuleCard(Output):
    module_id: uuid.UUID
    code: str
    title: str
    colour: str | None
    progress: MetricOut
    coverage: MetricOut
    mastered: MetricOut
    answered: MetricOut
    accuracy: MetricOut


class RecentUpload(Output):
    id: uuid.UUID
    filename: str
    module_code: str
    status: str
    created_at: datetime


class RecentMaterial(Output):
    id: uuid.UUID
    title: str
    kind: str
    origin: str
    module_code: str
    created_at: datetime


class OverviewOut(Output):
    today: TodayOut
    streak: StreakOut
    recent: SummaryOut
    mastered: MetricOut
    mistake_groups: MetricOut
    modules: list[ModuleCard]
    strong: list[TopicStat]
    weak: list[TopicStat]
    uploads: list[RecentUpload]
    materials: list[RecentMaterial]


class WeekOut(Output):
    start: date
    answered: int
    accuracy: float | None
    study_minutes: int
    reviews: int
    sessions_done: int
    sessions_planned: int
    mistakes: dict[str, int]


class DayActivity(Output):
    day: date
    events: int


class TrendsOut(Output):
    weeks: list[WeekOut]
    days: list[DayActivity]
    mistake_labels: dict[str, str]
    # One sentence per chart: what it is computed from.
    basis: dict[str, str]


class ReadinessOut(Output):
    exam_id: uuid.UUID
    module_id: uuid.UUID
    module_code: str
    title: str
    days_until: int
    index: float
    band: str
    components: dict[str, MetricOut]
    weak_topics: list[TopicStat]
    note: str


class ModuleAnalyticsOut(Output):
    module_id: uuid.UUID
    progress: MetricOut
    coverage: MetricOut
    mastered: MetricOut
    recent: SummaryOut
    readiness: ReadinessOut | None
    recommendation: BuiltBlock | None
