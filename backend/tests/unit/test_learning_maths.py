"""The adaptive-learning formulas: property tests (Hypothesis) and FSRS."""

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.config import get_config
from app.learning import maths, scheduling
from app.models import Flashcard

LEARNING = get_config().learning
MASTERY = LEARNING.mastery
DIFFICULTY = LEARNING.difficulty

difficulties = st.sampled_from(["easy", "medium", "hard", "exam"])
evidence = st.builds(
    maths.Evidence,
    score=st.floats(0, 1),
    difficulty=difficulties,
    age_days=st.floats(0, 400),
    low_confidence=st.booleans(),
)


@given(st.lists(evidence, max_size=40), st.none() | st.floats(0, 1))
def test_strength_stays_between_0_and_1(items: list[maths.Evidence], recall: float | None) -> None:
    p_hat, weight = maths.smoothed_accuracy(items, MASTERY)
    assert 0 <= p_hat <= 1 and weight >= 0
    assert 0 <= maths.strength(p_hat, recall, MASTERY) <= 1


@given(st.lists(evidence, min_size=1, max_size=30), st.integers(0, 29), st.floats(0, 1))
def test_strength_rises_with_score(items: list[maths.Evidence], index: int, extra: float) -> None:
    index %= len(items)
    better = list(items)
    old = items[index]
    better[index] = maths.Evidence(
        min(1.0, old.score + extra), old.difficulty, old.age_days, old.low_confidence
    )
    assert (
        maths.smoothed_accuracy(better, MASTERY)[0]
        >= maths.smoothed_accuracy(items, MASTERY)[0] - 1e-12
    )


def test_one_right_answer_never_reads_as_certain() -> None:
    p_hat, _ = maths.smoothed_accuracy([maths.Evidence(1.0, "medium", 0)], MASTERY)
    assert MASTERY.prior_accuracy < p_hat < 1


@given(difficulties, st.floats(0, 200), st.floats(0.1, 200))
def test_older_answers_count_less(difficulty: str, age: float, later: float) -> None:
    young = maths.attempt_weight(maths.Evidence(1, difficulty, age), MASTERY)
    old = maths.attempt_weight(maths.Evidence(1, difficulty, age + later), MASTERY)
    assert old < young


def test_harder_and_surer_answers_count_more() -> None:
    weights = [
        maths.attempt_weight(maths.Evidence(1, d, 0), MASTERY)
        for d in ("easy", "medium", "hard", "exam")
    ]
    assert weights == sorted(weights) and len(set(weights)) == 4
    sure = maths.attempt_weight(maths.Evidence(1, "medium", 0), MASTERY)
    unsure = maths.attempt_weight(maths.Evidence(1, "medium", 0, low_confidence=True), MASTERY)
    assert unsure < sure
    # Half-life: after h days an answer counts half.
    half = maths.attempt_weight(maths.Evidence(1, "medium", MASTERY.half_life_days), MASTERY)
    assert half == pytest.approx(sure / 2)


@given(st.floats(800, 2200), st.floats(800, 2200))
def test_elo_is_symmetric_and_moves_the_right_way(ability: float, rating: float) -> None:
    p = maths.expected_score(ability, rating)
    assert p + maths.expected_score(rating, ability) == pytest.approx(1)
    up, harder = maths.elo_update(ability, rating, 1.0, DIFFICULTY)
    down, easier = maths.elo_update(ability, rating, 0.0, DIFFICULTY)
    assert up >= ability >= down
    assert easier >= rating >= harder


def test_a_question_in_the_target_band_is_preferred() -> None:
    ability = 1500.0
    band = DIFFICULTY.target_success
    in_band = next(
        r for r in range(1000, 2000, 5) if band.min <= maths.expected_score(ability, r) <= band.max
    )
    too_easy, too_hard = 1000.0, 2000.0
    distances = [
        maths.target_distance(ability, r, DIFFICULTY) for r in (in_band, too_easy, too_hard)
    ]
    assert distances[0] < distances[1] and distances[0] < distances[2]


@settings(max_examples=200)
@given(
    st.integers(0, 40),
    st.dictionaries(
        st.integers(0, 12),
        st.tuples(st.floats(0, 3), st.integers(0, 8), st.integers(0, 2)),
        max_size=12,
    ),
    st.integers(0, 2),
)
def test_allocation_respects_capacity_floors_and_total(
    total: int, buckets: dict[int, tuple[float, int, int]], floor: int
) -> None:
    priorities = {k: v[0] for k, v in buckets.items()}
    capacity = {k: v[1] for k, v in buckets.items()}
    groups = {k: f"m{v[2]}" for k, v in buckets.items()}
    result = maths.allocate(total, priorities, capacity, groups, floor)
    assert sum(result.values()) == min(total, sum(capacity.values()))
    assert all(0 < n <= capacity[k] for k, n in result.items())
    # Every module with room gets its floor (while questions remain).
    if total >= floor * len(set(groups.values())):
        for group in set(groups.values()):
            room = sum(capacity[k] for k in buckets if groups[k] == group)
            got = sum(n for k, n in result.items() if groups[k] == group)
            assert got >= min(floor, room)


def test_equal_priorities_spread_evenly() -> None:
    result = maths.allocate(10, dict.fromkeys("abcd", 1.0), dict.fromkeys("abcd", 10))
    assert sorted(result.values()) == [2, 2, 3, 3]


def test_higher_priority_gets_more() -> None:
    result = maths.allocate(12, {"weak": 2.0, "strong": 0.5}, {"weak": 20, "strong": 20})
    assert result["weak"] > result["strong"] > 0


@given(st.none() | st.floats(0, 100), st.integers(0, 20))
def test_overdue_and_gap_are_fractions(days: float | None, attempts: int) -> None:
    assert 0 <= maths.overdue(days, 7) <= 1
    assert 0 <= maths.coverage_gap(attempts, 3) <= 1


# --- FSRS ---------------------------------------------------------------------------------


def _card(now: datetime) -> Flashcard:
    return Flashcard(fsrs_state=1, fsrs_step=0, due=now, reps=0, lapses=0)


def test_intervals_grow_after_good_and_lapse_after_again() -> None:
    config = LEARNING.spaced_repetition.model_copy(update={"fuzz": False})
    now = datetime(2026, 10, 1, 9, tzinfo=UTC)
    card = _card(now)
    gaps = []
    for _ in range(5):
        review = scheduling.review(card, 3, now, config)
        gaps.append(review.scheduled_days)
        now = card.due
    assert gaps == sorted(gaps) and gaps[-1] > 20
    assert card.fsrs_state == 2 and card.reps == 5 and card.lapses == 0

    review = scheduling.review(card, 1, now, config)
    assert card.fsrs_state == 3 and card.lapses == 1
    assert review.scheduled_days < 1  # back to a short relearning step
    assert review.state_before == 2 and review.elapsed_days is not None


def test_rating_previews_order_and_recall_fades() -> None:
    config = LEARNING.spaced_repetition
    now = datetime(2026, 10, 1, 9, tzinfo=UTC)
    card = _card(now)
    for _ in range(3):
        scheduling.review(card, 3, now, config.model_copy(update={"fuzz": False}))
        now = card.due
    preview = scheduling.preview(card, now, config)
    assert preview[1] < preview[2] < preview[3] < preview[4]
    soon = scheduling.retrievability(card, now, config)
    later = scheduling.retrievability(card, now + timedelta(days=60), config)
    assert soon is not None and later is not None and later < soon <= 1
    assert scheduling.retrievability(_card(now), now, config) is None
