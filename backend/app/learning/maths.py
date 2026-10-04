"""The adaptive-learning formulas (docs/algorithms.md; ARCHITECTURE.md section 10).

Pure functions of numbers: no database, no clock. Every tunable number comes
from config/learning.yaml.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.core.config import DifficultyConfig, MasteryConfig, PriorityWeights

ELO_SCALE = 400.0


@dataclass(frozen=True)
class Evidence:
    """One marked answer, as the formulas see it."""

    score: float  # 0-1
    difficulty: str  # easy | medium | hard | exam
    age_days: float
    low_confidence: bool = False


def attempt_weight(evidence: Evidence, config: MasteryConfig) -> float:
    """w = d * 2^(-age / h), times the low-confidence factor for unsure AI marks."""
    d = float(getattr(config.difficulty_weights, evidence.difficulty))
    w = d * 2 ** (-max(evidence.age_days, 0.0) / config.half_life_days)
    return w * (config.low_confidence_mark_weight if evidence.low_confidence else 1.0)


def smoothed_accuracy(evidence: Iterable[Evidence], config: MasteryConfig) -> tuple[float, float]:
    """(p_hat, total weight): accuracy pulled towards the prior p0 with
    weight alpha, so one right answer never reads as 100%."""
    total = weighted = 0.0
    for item in evidence:
        w = attempt_weight(item, config)
        total += w
        weighted += w * min(max(item.score, 0.0), 1.0)
    alpha, p0 = config.prior_weight, config.prior_accuracy
    return (weighted + alpha * p0) / (total + alpha), total


def strength(p_hat: float, retrievability: float | None, config: MasteryConfig) -> float:
    """lambda * p_hat + (1 - lambda) * mean flashcard retrievability (if any)."""
    if retrievability is None:
        return p_hat
    lam = config.flashcard_blend_lambda
    return lam * p_hat + (1 - lam) * retrievability


def expected_score(ability: float, rating: float) -> float:
    """P(correct) = 1 / (1 + 10^((b - theta) / 400))."""
    return 1.0 / (1.0 + 10 ** ((rating - ability) / ELO_SCALE))


def elo_update(
    ability: float, rating: float, score: float, config: DifficultyConfig, weight: float = 1.0
) -> tuple[float, float]:
    """After one answer: theta moves by K_a(s - P); b moves the other way by K_q(s - P)."""
    surprise = score - expected_score(ability, rating)
    return (
        ability + weight * config.k_ability * surprise,
        rating - weight * config.k_question * surprise,
    )


def target_distance(ability: float, rating: float, config: DifficultyConfig) -> float:
    """How far a question's predicted success is from the target band
    (0 inside it), plus a little distance from the band's middle."""
    p = expected_score(ability, rating)
    band = config.target_success
    outside = max(band.min - p, p - band.max, 0.0)
    return outside + 0.01 * abs(p - (band.min + band.max) / 2)


@dataclass(frozen=True)
class PriorityTerms:
    """Each term is in [0, 1]."""

    weakness: float  # 1 - strength
    overdue: float
    urgency: float
    recurring: float
    gap: float

    def total(self, weights: PriorityWeights) -> float:
        return (
            weights.weakness * self.weakness
            + weights.overdue * self.overdue
            + weights.urgency * self.urgency
            + weights.recurring * self.recurring
            + weights.gap * self.gap
        )


def overdue(days_since: float | None, after_days: float) -> float:
    """0 just after practice, rising to 1 at `after_days` (and for never)."""
    if days_since is None:
        return 1.0
    return min(1.0, max(days_since, 0.0) / after_days)


def coverage_gap(attempts: int, coverage_attempts: int) -> float:
    return 1.0 - min(1.0, attempts / coverage_attempts)


def allocate[K](
    total: int,
    priorities: Mapping[K, float],
    capacity: Mapping[K, int],
    groups: Mapping[K, str] | None = None,
    group_floor: int = 0,
) -> dict[K, int]:
    """Split `total` questions across buckets in proportion to priority,
    never giving a bucket more than its capacity, and first giving every
    group (module) `group_floor` questions in its highest-priority bucket.
    Largest-remainder rounding; the result sums to min(total, capacity)."""
    keys = [k for k in priorities if capacity.get(k, 0) > 0]
    result = dict.fromkeys(keys, 0)
    remaining = min(total, sum(capacity[k] for k in keys))

    if groups and group_floor:
        by_group: dict[str, list[K]] = {}
        for k in keys:
            by_group.setdefault(groups[k], []).append(k)
        for members in sorted(by_group.values(), key=lambda m: -max(priorities[k] for k in m)):
            for _ in range(group_floor):
                if remaining <= 0:
                    break
                open_ = [k for k in members if result[k] < capacity[k]]
                if not open_:
                    break
                best = max(open_, key=lambda k: priorities[k])
                result[best] += 1
                remaining -= 1

    while remaining > 0:
        open_ = [k for k in keys if result[k] < capacity[k]]
        if not open_:
            break
        weight = sum(max(priorities[k], 1e-9) for k in open_)
        shares = {k: remaining * max(priorities[k], 1e-9) / weight for k in open_}
        given = 0
        for k in open_:
            extra = min(math.floor(shares[k]), capacity[k] - result[k])
            result[k] += extra
            given += extra
        remaining -= given
        if given == 0:
            # Hand out the remainder one at a time, largest fraction first.
            for k in sorted(open_, key=lambda k: (-(shares[k] % 1), -priorities[k])):
                if remaining <= 0:
                    break
                if result[k] < capacity[k]:
                    result[k] += 1
                    remaining -= 1
    return {k: n for k, n in result.items() if n > 0}


def median(values: Sequence[float]) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
