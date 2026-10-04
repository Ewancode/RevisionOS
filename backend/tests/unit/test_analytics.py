"""The analytics computations: properties that make every figure traceable."""

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from hypothesis import given
from hypothesis import strategies as st

from app.analytics import compute
from app.analytics.compute import Answer, Metric, Review, Session
from app.core.config import get_config

CONFIG = get_config().analytics
ZONE = ZoneInfo("Europe/London")
TODAY = date(2026, 10, 5)  # a Monday
NOW = datetime(2026, 10, 5, 11, tzinfo=UTC)
MODULE = uuid.uuid4()

days = st.sets(st.integers(min_value=0, max_value=60).map(lambda n: TODAY - timedelta(days=n)))


@given(days)
def test_streaks_are_runs_of_consecutive_days(active: set[date]) -> None:
    current, longest = compute.streaks(active, TODAY)
    assert 0 <= current <= longest <= len(active)
    # The current run ends today or yesterday, and every day in it was active.
    end = TODAY if TODAY in active else TODAY - timedelta(days=1)
    assert all(end - timedelta(days=i) in active for i in range(current))
    assert end - timedelta(days=current) not in active
    # Some run of `longest` consecutive days exists.
    if longest:
        assert any(all(d + timedelta(days=i) in active for i in range(longest)) for d in active)


def test_a_streak_survives_until_today_is_over() -> None:
    yesterday = {TODAY - timedelta(days=n) for n in (1, 2, 3)}
    assert compute.streaks(yesterday, TODAY) == (3, 3)
    assert compute.streaks(yesterday | {TODAY}, TODAY) == (4, 4)
    assert compute.streaks({TODAY - timedelta(days=2)}, TODAY) == (0, 1)
    current, _ = compute.streak_metrics(yesterday, TODAY)
    assert current.value == 3 and "since Fri 02 Oct (nothing yet today)" in current.basis


def _answer(
    score: float, at: datetime, ms: int | None = 60_000, mistake: str | None = None
) -> Answer:
    return Answer(MODULE, None, score, at, ms, mistake, "practice", uuid.uuid4())


@given(st.lists(st.one_of(st.none(), st.integers(min_value=1, max_value=10**8)), max_size=30))
def test_study_time_is_capped_and_counts_only_recorded_time(times: list[int | None]) -> None:
    answers = [_answer(1.0, NOW, ms) for ms in times]
    metric = compute.study_minutes(answers, [], CONFIG)
    cap = CONFIG.study_time.answer_cap_minutes * 60_000
    assert metric.value == round(sum(min(t, cap) for t in times if t) / 60_000)
    timed = sum(1 for t in times if t)
    assert f"Recorded time of {compute.plural(timed, 'answer')}" in metric.basis
    if timed < len(times):
        assert f"{len(times) - timed} without a recorded time not counted" in metric.basis


def test_a_summary_names_what_it_counted() -> None:
    answers = [
        _answer(1.0, NOW),
        _answer(1.0, NOW),
        _answer(0.5, NOW, mistake="sign_error"),
        _answer(0.0, NOW, mistake="sign_error"),
    ]
    reviews = [Review(MODULE, NOW, 30_000, 3)]
    s = compute.summarise(
        answers, reviews, label="in the last 7 days", correct_at=0.999, config=CONFIG
    )
    assert (s.answered.value, s.correct.value, s.reviews.value) == (4, 2, 1)
    assert s.accuracy.value == 0.625
    assert (
        s.accuracy.basis
        == "Mean mark of 4 answers marked in the last 7 days (partial credit counts)"
    )
    assert s.study_minutes.value == round((4 * 60_000 + 30_000) / 60_000)
    assert s.mistakes.value == 2 and s.mistakes.basis.endswith(": sign error 2")
    empty = compute.summarise([], [], label="in the last 7 days", correct_at=0.999, config=CONFIG)
    assert empty.accuracy == Metric(None, "No answers marked in the last 7 days")


offsets = st.integers(min_value=-120, max_value=0)


@given(
    st.lists(st.tuples(offsets, st.floats(min_value=0, max_value=1)), max_size=40),
    st.lists(offsets, max_size=40),
    st.lists(
        st.tuples(offsets, st.sampled_from(["done", "missed", "skipped", "planned"])), max_size=20
    ),
)
def test_weekly_buckets_add_up_to_the_events_in_range(
    answer_days: list[tuple[int, float]],
    review_days: list[int],
    session_days: list[tuple[int, str]],
) -> None:
    def at(offset: int) -> datetime:
        return datetime.combine(
            TODAY + timedelta(days=offset), datetime.min.time(), ZONE
        ) + timedelta(hours=12)

    answers = [_answer(score, at(o)) for o, score in answer_days]
    reviews = [Review(MODULE, at(o), None, 3) for o in review_days]
    sessions = [
        Session(MODULE, TODAY + timedelta(days=o), status, 45) for o, status in session_days
    ]
    weeks = compute.weekly(
        answers, reviews, sessions, today=TODAY, zone=ZONE, correct_at=0.999, config=CONFIG
    )
    assert len(weeks) == CONFIG.windows.chart_weeks
    assert weeks[-1].start == TODAY and weeks[0].start == TODAY - timedelta(
        weeks=CONFIG.windows.chart_weeks - 1
    )
    first = weeks[0].start
    in_range = [(o, s) for o, s in answer_days if TODAY + timedelta(days=o) >= first]
    assert sum(w.answered for w in weeks) == len(in_range)
    assert abs(sum(w.score_sum for w in weeks) - sum(s for _, s in in_range)) < 1e-9
    assert sum(w.reviews for w in weeks) == sum(
        1 for o in review_days if TODAY + timedelta(days=o) >= first
    )
    past = [
        (o, s)
        for o, s in session_days
        if TODAY + timedelta(days=o) >= first and not (o == 0 and s == "planned")
    ]
    assert sum(w.sessions_planned for w in weeks) == len(past)
    assert sum(w.sessions_done for w in weeks) == sum(1 for _, s in past if s == "done")
    for w in weeks:
        if w.answered:
            assert w.accuracy is not None and 0 <= w.accuracy <= 1
        else:
            assert w.accuracy is None


@given(
    st.dictionaries(
        st.sampled_from(["coverage", "strength", "recent", "mock", "recency"]),
        st.one_of(st.none(), st.floats(min_value=0, max_value=1)),
        min_size=5,
    )
)
def test_readiness_is_a_weighted_mean_of_what_was_measured(values: dict[str, float | None]) -> None:
    config = CONFIG.readiness
    result = compute.combine({k: Metric(v, "b") for k, v in values.items()}, config)
    present = {k: v for k, v in values.items() if v is not None}
    weights = config.weights.model_dump()
    assert 0 <= result.index <= 1
    if present:
        expected = sum(weights[k] * v for k, v in present.items()) / sum(
            weights[k] for k in present
        )
        assert abs(result.index - expected) < 1e-9
        assert min(present.values()) - 1e-9 <= result.index <= max(present.values()) + 1e-9
    labels = [label for threshold, label in config.bands if result.index >= threshold]
    assert result.band == labels[-1]


def test_readiness_components_explain_themselves() -> None:
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    topics = [
        compute.TopicState(t1, "Series", 0.8, 5, NOW - timedelta(days=2)),
        compute.TopicState(t2, "Limits", 0.4, 1, NOW - timedelta(days=20)),
    ]
    answers = [_answer(1.0, NOW - timedelta(days=1)), _answer(0.5, NOW - timedelta(days=30))]
    r = compute.readiness(
        topics, answers, [0.7, 0.5, 0.3, 0.1], now=NOW, coverage_attempts=3, config=CONFIG.readiness
    )
    c = r.components
    assert (c["coverage"].value, c["recency"].value) == (0.5, 0.5)
    assert abs(c["strength"].value - 0.6) < 1e-9  # type: ignore[operator]
    assert c["recent"].value == 1.0  # only the answer within 14 days
    assert abs(c["mock"].value - 0.5) < 1e-9  # type: ignore[operator]  # latest three
    assert c["coverage"].basis == "1 of 2 exam topics with at least 3 marked answers"
    assert c["mock"].basis == "Mean score of the latest 3 marked mock exams"
    none = compute.readiness(topics, [], [], now=NOW, coverage_attempts=3, config=CONFIG.readiness)
    assert none.components["mock"].value is None and none.components["recent"].value is None
    assert none.components["mock"].basis == "No marked mock exams for this module yet"
