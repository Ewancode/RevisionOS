"""The revision-plan allocator (ARCHITECTURE.md section 11, "Allocation").

A pure, deterministic function: the same inputs always give the same plan,
and no AI is involved. The planner service builds the inputs from your
exams, availability, topic strengths and locked sessions.

1. Each topic has a need in minutes (computed by the service from exam
   weighting, weakness, coverage and your confidence).
2. A mock exam goes a few days before each exam.
3. Days are filled in order, greedily by priority:
   priority = need left / scale * urgency(days to exam) * boosts, where
   urgency = 1 / (1 + days / half_days) rises as the exam nears, and a
   second block of the same module in a row is damped (modules interleave).
   Exam topics with no block yet come first outright, so every exam topic
   gets time before any gets a second block.
4. Rules: at most one block per topic per day; the same topic at least
   `min_gap_days` apart except in its exam's final days; nothing for a topic
   on or after its exam's day; never more than a day's capacity or
   `max_sessions` blocks.
5. Locked sessions (ones you moved) are fixed: they use their day's capacity
   and count towards their topic's need.
6. Where need exceeds capacity before an exam, the shortfall is reported
   (with the topics left out) instead of cramming.
"""

import math
import uuid
from dataclasses import dataclass, field
from datetime import date

from app.core.config import AllocationConfig

Key = tuple[uuid.UUID, uuid.UUID | None]  # (module, topic or None)


@dataclass(frozen=True)
class Day:
    day: date
    # Minutes free for revision blocks (after flashcard and quiz reserves).
    capacity: int


@dataclass(frozen=True)
class TopicNeed:
    module_id: uuid.UUID
    topic_id: uuid.UUID | None
    title: str
    need_minutes: int
    exam_id: uuid.UUID | None = None
    exam_day: date | None = None
    # Multiplies priority (e.g. low for upkeep of modules with no exam).
    priority_factor: float = 1.0

    @property
    def key(self) -> Key:
        return (self.module_id, self.topic_id)


@dataclass(frozen=True)
class Locked:
    day: date
    minutes: int
    module_id: uuid.UUID
    topic_id: uuid.UUID | None

    @property
    def key(self) -> Key:
        return (self.module_id, self.topic_id)


@dataclass(frozen=True)
class ExamSlot:
    exam_id: uuid.UUID
    module_id: uuid.UUID
    day: date
    duration_minutes: int
    title: str


@dataclass(frozen=True)
class Planned:
    day: date
    module_id: uuid.UUID
    topic_id: uuid.UUID | None
    kind: str  # topic | mock_exam
    minutes: int
    exam_id: uuid.UUID | None = None


@dataclass
class Shortfall:
    exam_id: uuid.UUID
    title: str
    needed_minutes: int
    planned_minutes: int
    available_minutes: int
    left_out: list[str] = field(default_factory=list)
    # "time": not enough free time before the exam; "spacing": there is time,
    # but the spacing rules (one block per topic per day, days apart) limit
    # how often a topic can come up: longer sessions would help.
    reason: str = "time"


def urgency(days_to_exam: int | None, half_days: float) -> float:
    if days_to_exam is None:
        return 1.0
    return 1.0 / (1.0 + max(days_to_exam, 0) / half_days)


def _round5(minutes: float) -> int:
    return int(math.ceil(minutes / 5.0) * 5)


def allocate(
    days: list[Day],
    needs: list[TopicNeed],
    locked: list[Locked],
    exams: list[ExamSlot],
    config: AllocationConfig,
    *,
    session_minutes: int,
    max_sessions: int,
) -> tuple[list[Planned], list[Shortfall]]:
    by_day = {d.day: d for d in days}
    left = {d.day: d.capacity for d in days}
    count = dict.fromkeys(by_day, 0)
    remaining = {n.key: float(n.need_minutes) for n in needs}
    need_of = {n.key: n for n in needs}
    last: dict[Key, date] = {}
    covered: set[Key] = set()
    planned: list[Planned] = []

    for fixed in locked:
        if fixed.day in left:
            left[fixed.day] -= fixed.minutes
            count[fixed.day] += 1
        if fixed.key in remaining:
            remaining[fixed.key] -= fixed.minutes
            covered.add(fixed.key)
            if fixed.key not in last or fixed.day > last[fixed.key]:
                last[fixed.key] = fixed.day

    # Mock exams: one, a few days before each exam, on the nearest day with room.
    for exam in sorted(exams, key=lambda e: e.day):
        target = exam.day.toordinal() - config.mock_exam_days_before
        options = sorted(
            (d for d in by_day if d < exam.day),
            key=lambda d: (abs(d.toordinal() - target), -d.toordinal()),
        )
        for d in options:
            minutes = min(exam.duration_minutes, left[d])
            if minutes >= config.min_block_minutes and count[d] < max_sessions:
                planned.append(Planned(d, exam.module_id, None, "mock_exam", minutes, exam.exam_id))
                left[d] -= minutes
                count[d] += 1
                break

    scale = float(config.need_scale_minutes)
    for d in sorted(by_day):
        previous_module: uuid.UUID | None = None
        today: set[Key] = set()
        while left[d] >= config.min_block_minutes and count[d] < max_sessions:
            best: tuple[bool, float, str, Key] | None = None
            for key, need in need_of.items():
                if remaining[key] <= 0 or key in today:
                    continue
                if need.exam_day is not None and d >= need.exam_day:
                    continue
                days_to = (need.exam_day - d).days if need.exam_day else None
                if key in last:
                    gap = (d - last[key]).days
                    final = days_to is not None and days_to <= config.final_days
                    if gap < config.min_gap_days and not final:
                        continue
                priority = (
                    remaining[key] / scale
                    * urgency(days_to, config.urgency_half_days)
                    * need.priority_factor
                )  # fmt: skip
                if previous_module == key[0]:
                    priority *= config.same_module_penalty
                first = need.exam_id is not None and key not in covered
                candidate = (first, priority, f"{key[0]}:{key[1]}", key)
                if best is None or candidate[:3] > best[:3]:
                    best = candidate
            if best is None:
                break
            key = best[3]
            block = min(
                session_minutes, left[d], max(_round5(remaining[key]), config.min_block_minutes)
            )
            if block < config.min_block_minutes:
                break
            need = need_of[key]
            planned.append(Planned(d, key[0], key[1], "topic", block, need.exam_id))
            remaining[key] -= block
            left[d] -= block
            count[d] += 1
            last[key] = d
            covered.add(key)
            today.add(key)
            previous_module = key[0]

    shortfalls = []
    for exam in exams:
        topics = [n for n in needs if n.exam_id == exam.exam_id]
        needed = sum(n.need_minutes for n in topics)
        unmet = sum(max(remaining[n.key], 0.0) for n in topics)
        if unmet >= config.min_block_minutes:
            available = sum(by_day[d].capacity for d in by_day if d < exam.day)
            left_out = sorted(
                (n for n in topics if n.key not in covered), key=lambda n: n.need_minutes
            )
            shortfalls.append(
                Shortfall(
                    exam_id=exam.exam_id,
                    title=exam.title,
                    needed_minutes=needed,
                    planned_minutes=int(needed - unmet),
                    available_minutes=available,
                    left_out=[n.title for n in left_out],
                    reason="time" if available < needed else "spacing",
                )
            )
    planned.sort(key=lambda p: (p.day, p.kind != "mock_exam"))
    return planned, shortfalls
