"""Analytics from stored events: pure functions, no database, no AI.

Every figure is returned with its *basis*: a sentence naming the stored rows
it was computed from ("16 of 20 answers marked in the last 7 days"), so each
number on screen can be traced back (the Phase 9 acceptance criterion).

Days are local days in the student's time zone; weeks start on Monday.
"""

import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import AnalyticsConfig, ReadinessConfig
from app.learning.mistakes import CATEGORY_LABELS

# --- inputs ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Answer:
    """A marked answer."""

    module_id: uuid.UUID
    topic_id: uuid.UUID | None
    score: float
    marked_at: datetime
    time_ms: int | None
    mistake: str | None
    quiz_kind: str  # practice | mock | daily
    attempt_id: uuid.UUID


@dataclass(frozen=True)
class Review:
    """A flashcard review."""

    module_id: uuid.UUID
    reviewed_at: datetime
    duration_ms: int | None
    rating: int


@dataclass(frozen=True)
class Session:
    """A planned revision session."""

    module_id: uuid.UUID
    day: date
    status: str  # planned | done | missed | skipped
    minutes: int


# --- outputs -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Metric:
    value: float | None
    basis: str


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def local_day(at: datetime, zone: ZoneInfo) -> date:
    return at.astimezone(zone).date()


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


# --- activity and streaks -------------------------------------------------------------------


def activity_by_day(
    answers: Iterable[Answer],
    reviews: Iterable[Review],
    sessions: Iterable[Session],
    zone: ZoneInfo,
) -> Counter[date]:
    """Study events per local day: marked answers, card reviews and sessions done."""
    days: Counter[date] = Counter()
    for a in answers:
        days[local_day(a.marked_at, zone)] += 1
    for r in reviews:
        days[local_day(r.reviewed_at, zone)] += 1
    for s in sessions:
        if s.status == "done":
            days[s.day] += 1
    return days


def streaks(active: set[date], today: date) -> tuple[int, int]:
    """(current, longest) runs of consecutive active days. The current run
    may end yesterday: today still counts until it is over."""
    current = 0
    day = today if today in active else today - timedelta(days=1)
    while day in active:
        current += 1
        day -= timedelta(days=1)
    longest = run = 0
    previous: date | None = None
    for day in sorted(active):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
    return current, longest


def streak_metrics(active: set[date], today: date) -> tuple[Metric, Metric]:
    current, longest = streaks(active, today)
    if current:
        start = (today if today in active else today - timedelta(days=1)) - timedelta(
            days=current - 1
        )
        basis = (
            f"{plural(current, 'day')} in a row with at least one answer, flashcard review "
            f"or completed session, since {start:%a %d %b}"
        )
        if today not in active:
            basis += " (nothing yet today)"
    else:
        basis = "No answers, flashcard reviews or completed sessions today or yesterday"
    return (
        Metric(current, basis),
        Metric(longest, f"Longest run of active days across {plural(len(active), 'active day')}"),
    )


# --- study time -------------------------------------------------------------------------------


def study_minutes(
    answers: Sequence[Answer], reviews: Sequence[Review], config: AnalyticsConfig
) -> Metric:
    caps = config.study_time
    answer_ms = [min(a.time_ms, caps.answer_cap_minutes * 60_000) for a in answers if a.time_ms]
    review_ms = [
        min(r.duration_ms, caps.review_cap_seconds * 1000) for r in reviews if r.duration_ms
    ]
    minutes = round((sum(answer_ms) + sum(review_ms)) / 60_000)
    untimed = (len(answers) - len(answer_ms)) + (len(reviews) - len(review_ms))
    basis = (
        f"Recorded time of {plural(len(answer_ms), 'answer')} and "
        f"{plural(len(review_ms), 'flashcard review')} (each capped at "
        f"{caps.answer_cap_minutes} min and {caps.review_cap_seconds} s)"
    )
    if untimed:
        basis += f"; {untimed} without a recorded time not counted"
    return Metric(minutes, basis)


# --- summaries over a window -------------------------------------------------------------------


@dataclass(frozen=True)
class Summary:
    answered: Metric
    correct: Metric
    accuracy: Metric
    study_minutes: Metric
    reviews: Metric
    mistakes: Metric


def summarise(
    answers: Sequence[Answer],
    reviews: Sequence[Review],
    *,
    label: str,
    correct_at: float,
    config: AnalyticsConfig,
) -> Summary:
    """Figures for answers and reviews already filtered to a window ("in the
    last 7 days")."""
    n = len(answers)
    correct = sum(1 for a in answers if a.score >= correct_at)
    mistakes = Counter(a.mistake for a in answers if a.mistake and a.score < correct_at)
    accuracy = (
        Metric(
            sum(a.score for a in answers) / n,
            f"Mean mark of {plural(n, 'answer')} marked {label} (partial credit counts)",
        )
        if n
        else Metric(None, f"No answers marked {label}")
    )
    top = ", ".join(f"{CATEGORY_LABELS.get(c, c).lower()} {k}" for c, k in mistakes.most_common(3))
    return Summary(
        answered=Metric(n, f"Answers marked {label}"),
        correct=Metric(correct, f"Answers marked {label} with full marks ({correct} of {n})"),
        accuracy=accuracy,
        study_minutes=study_minutes(answers, reviews, config),
        reviews=Metric(len(reviews), f"Flashcard reviews {label}"),
        mistakes=Metric(
            sum(mistakes.values()),
            f"Answers marked {label} with a classified mistake" + (f": {top}" if top else ""),
        ),
    )


# --- weekly trends --------------------------------------------------------------------------------


@dataclass
class Week:
    start: date
    answered: int = 0
    score_sum: float = 0.0
    study_ms: int = 0
    reviews: int = 0
    sessions_done: int = 0
    sessions_planned: int = 0  # past sessions: done, missed or skipped
    mistakes: Counter[str] = field(default_factory=Counter)

    @property
    def accuracy(self) -> float | None:
        return self.score_sum / self.answered if self.answered else None


def weekly(
    answers: Iterable[Answer],
    reviews: Iterable[Review],
    sessions: Iterable[Session],
    *,
    today: date,
    zone: ZoneInfo,
    correct_at: float,
    config: AnalyticsConfig,
) -> list[Week]:
    """The last `chart_weeks` weeks, oldest first, this week included."""
    caps = config.study_time
    first = week_start(today) - timedelta(weeks=config.windows.chart_weeks - 1)
    weeks = {
        first + timedelta(weeks=i): Week(first + timedelta(weeks=i))
        for i in range(config.windows.chart_weeks)
    }

    def bucket(day: date) -> Week | None:
        return weeks.get(week_start(day))

    for a in answers:
        w = bucket(local_day(a.marked_at, zone))
        if w is None:
            continue
        w.answered += 1
        w.score_sum += a.score
        if a.time_ms:
            w.study_ms += min(a.time_ms, caps.answer_cap_minutes * 60_000)
        if a.mistake and a.score < correct_at:
            w.mistakes[a.mistake] += 1
    for r in reviews:
        w = bucket(local_day(r.reviewed_at, zone))
        if w is None:
            continue
        w.reviews += 1
        if r.duration_ms:
            w.study_ms += min(r.duration_ms, caps.review_cap_seconds * 1000)
    for s in sessions:
        w = bucket(s.day)
        if w is None or s.day > today or (s.day == today and s.status == "planned"):
            continue
        w.sessions_planned += 1
        if s.status == "done":
            w.sessions_done += 1
    return list(weeks.values())


# --- exam readiness ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Readiness:
    index: float
    band: str
    components: dict[str, Metric]


def combine(components: dict[str, Metric], config: ReadinessConfig) -> Readiness:
    """Weighted mean of the components that have a value; the weights of
    missing ones (no mock taken yet, say) are left out, not counted as zero."""
    weights = config.weights.model_dump()
    present = {k: m.value for k, m in components.items() if m.value is not None and weights[k] > 0}
    total = sum(weights[k] for k in present)
    index = sum(weights[k] * float(v) for k, v in present.items()) / total if total else 0.0
    band = config.bands[0][1]
    for threshold, label in config.bands:
        if index >= threshold:
            band = label
    return Readiness(index, band, components)


@dataclass(frozen=True)
class TopicState:
    topic_id: uuid.UUID | None
    title: str
    strength: float
    answers: int
    last_practised: datetime | None


def readiness(
    topics: Sequence[TopicState],
    answers: Sequence[Answer],
    mock_scores: Sequence[float],
    *,
    now: datetime,
    coverage_attempts: int,
    config: ReadinessConfig,
) -> Readiness:
    """`topics` are the exam's topics; `answers` those on its topics; `mock_scores`
    the module's latest marked mock exams, newest first."""
    n = len(topics)
    covered = [t for t in topics if t.answers >= coverage_attempts]
    recent_cut = now - timedelta(days=config.recent_days)
    recent = [a for a in answers if a.marked_at >= recent_cut]
    fresh_cut = now - timedelta(days=config.recency_days)
    fresh = [t for t in topics if t.last_practised and t.last_practised >= fresh_cut]
    mocks = list(mock_scores[: config.mock_attempts])
    components = {
        "coverage": Metric(
            len(covered) / n if n else None,
            f"{len(covered)} of {plural(n, 'exam topic')} with at least "
            f"{coverage_attempts} marked answers",
        ),
        "strength": Metric(
            sum(t.strength for t in topics) / n if n else None,
            f"Mean estimated strength of the {plural(n, 'exam topic')}",
        ),
        "recent": Metric(
            sum(a.score for a in recent) / len(recent) if recent else None,
            f"Mean mark of {plural(len(recent), 'answer')} on the exam's topics in the last "
            f"{config.recent_days} days"
            if recent
            else f"No answers on the exam's topics in the last {config.recent_days} days",
        ),
        "mock": Metric(
            sum(mocks) / len(mocks) if mocks else None,
            f"Mean score of the latest {plural(len(mocks), 'marked mock exam')}"
            if mocks
            else "No marked mock exams for this module yet",
        ),
        "recency": Metric(
            len(fresh) / n if n else None,
            f"{len(fresh)} of {plural(n, 'exam topic')} practised in the last "
            f"{config.recency_days} days",
        ),
    }
    return combine(components, config)


def by_module[T: (Answer, Review, Session)](items: Iterable[T]) -> dict[uuid.UUID, list[T]]:
    grouped: dict[uuid.UUID, list[T]] = defaultdict(list)
    for item in items:
        grouped[item.module_id].append(item)
    return grouped
