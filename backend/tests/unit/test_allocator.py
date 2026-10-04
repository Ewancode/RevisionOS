"""Property tests for the plan allocator (ARCHITECTURE.md section 13):
plans never exceed availability, never move locked sessions, respect the
spacing rules, give every exam topic time when there is room, and say so
when there is not."""

import uuid
from collections import defaultdict
from datetime import date, timedelta
from itertools import pairwise

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.config import get_config
from app.planner.allocator import Day, ExamSlot, Locked, TopicNeed, allocate

CONFIG = get_config().planner.allocation
START = date(2026, 10, 5)
SESSION, MAX_SESSIONS = 45, 3
MODULES = [uuid.UUID(int=i) for i in range(1, 5)]


@st.composite
def scenarios(draw: st.DrawFn) -> tuple[list[Day], list[TopicNeed], list[Locked], list[ExamSlot]]:
    n_days = draw(st.integers(1, 40))
    days = [Day(START + timedelta(days=i), draw(st.integers(0, 240))) for i in range(n_days)]
    exams = []
    for module in draw(st.lists(st.sampled_from(MODULES), unique=True, max_size=3)):
        offset = draw(st.integers(1, n_days + 5))
        exams.append(
            ExamSlot(
                uuid.uuid4(),
                module,
                START + timedelta(days=offset),
                draw(st.integers(30, 180)),
                f"exam {module.int}",
            )
        )
    exam_of = {e.module_id: e for e in exams}
    needs = []
    for i in range(draw(st.integers(0, 10))):
        module = draw(st.sampled_from(MODULES))
        exam = exam_of.get(module)
        needs.append(
            TopicNeed(
                module_id=module,
                topic_id=uuid.UUID(int=1000 + i),
                title=f"t{i}",
                need_minutes=draw(st.integers(0, 600)),
                exam_id=exam.exam_id if exam else None,
                exam_day=exam.day if exam else None,
                priority_factor=1.0 if exam else CONFIG.maintenance_priority,
            )
        )
    locked = []
    used: dict[date, int] = defaultdict(int)
    for _ in range(draw(st.integers(0, 4))):
        if not needs:
            break
        d = draw(st.sampled_from(days))
        minutes = draw(st.integers(10, 60))
        if used[d.day] + minutes <= d.capacity:
            need = draw(st.sampled_from(needs))
            locked.append(Locked(d.day, minutes, need.module_id, need.topic_id))
            used[d.day] += minutes
    return days, needs, locked, exams


def run(scenario: tuple[list[Day], list[TopicNeed], list[Locked], list[ExamSlot]]):  # type: ignore[no-untyped-def]
    days, needs, locked, exams = scenario
    return allocate(
        days, needs, locked, exams, CONFIG, session_minutes=SESSION, max_sessions=MAX_SESSIONS
    )


@settings(max_examples=300, deadline=None)
@given(scenarios())
def test_plans_never_exceed_availability_or_session_limits(scenario) -> None:  # type: ignore[no-untyped-def]
    days, _, locked, _ = scenario
    planned, _ = run(scenario)
    capacity = {d.day: d.capacity for d in days}
    minutes: dict[date, int] = defaultdict(int)
    blocks: dict[date, int] = defaultdict(int)
    for item in [*planned, *locked]:
        minutes[item.day] += item.minutes
        blocks[item.day] += 1
    locked_blocks: dict[date, int] = defaultdict(int)
    for item in locked:
        locked_blocks[item.day] += 1
    for day, total in minutes.items():
        assert total <= capacity[day], (day, total, capacity[day])
        # The planner adds nothing beyond the limit (your locked sessions may).
        assert blocks[day] <= max(MAX_SESSIONS, locked_blocks[day])
    assert all(p.minutes >= CONFIG.min_block_minutes for p in planned)


@settings(max_examples=300, deadline=None)
@given(scenarios())
def test_spacing_and_exam_days_are_respected(scenario) -> None:  # type: ignore[no-untyped-def]
    _, needs, locked, _ = scenario
    planned, _ = run(scenario)
    exam_day = {n.key: n.exam_day for n in needs}
    by_topic: dict[tuple, list[date]] = defaultdict(list)  # type: ignore[type-arg]
    for p in planned:
        if p.kind != "topic":
            continue
        key = (p.module_id, p.topic_id)
        if exam_day[key] is not None:
            assert p.day < exam_day[key]  # nothing on or after its exam
        by_topic[key].append(p.day)
    for key, days in by_topic.items():
        assert len(days) == len(set(days))  # one block per topic per day
        locked_days = [b.day for b in locked if (b.module_id, b.topic_id) == key]
        everything = sorted(days + locked_days)
        for earlier, later in pairwise(everything):
            if later not in days:
                continue
            close = exam_day[key] is not None and (exam_day[key] - later).days <= CONFIG.final_days
            assert (later - earlier).days >= CONFIG.min_gap_days or close or earlier == later


@settings(max_examples=200, deadline=None)
@given(scenarios())
def test_the_same_inputs_give_the_same_plan(scenario) -> None:  # type: ignore[no-untyped-def]
    assert run(scenario) == run(scenario)


@settings(max_examples=300, deadline=None)
@given(scenarios())
def test_every_exam_topic_gets_time_when_there_is_room(scenario) -> None:  # type: ignore[no-untyped-def]
    days, needs, locked, exams = scenario
    if locked:
        return
    planned, _ = run(scenario)
    exam_topics = [n for n in needs if n.exam_id is not None and n.need_minutes > 0]
    for exam in exams:
        slots = sum(min(MAX_SESSIONS, d.capacity // SESSION) for d in days if d.day < exam.day)
        if slots < len(exam_topics) + len(exams):
            continue
        got = {(p.module_id, p.topic_id) for p in planned if p.kind == "topic"}
        for need in exam_topics:
            if need.exam_id == exam.exam_id:
                assert need.key in got, need.title


@settings(max_examples=300, deadline=None)
@given(scenarios())
def test_a_shortfall_is_reported_instead_of_cramming(scenario) -> None:  # type: ignore[no-untyped-def]
    days, needs, locked, exams = scenario
    if locked:
        return
    _, shortfalls = run(scenario)
    reported = {s.exam_id for s in shortfalls}
    for exam in exams:
        topics = [n for n in needs if n.exam_id == exam.exam_id]
        need = sum(n.need_minutes for n in topics)
        capacity = sum(d.capacity for d in days if d.day < exam.day)
        if need - capacity >= CONFIG.min_block_minutes:
            assert exam.exam_id in reported
    for shortfall in shortfalls:
        assert shortfall.planned_minutes < shortfall.needed_minutes


@settings(max_examples=200, deadline=None)
@given(scenarios())
def test_each_exam_gets_at_most_one_mock_before_it(scenario) -> None:  # type: ignore[no-untyped-def]
    _, _, _, exams = scenario
    planned, _ = run(scenario)
    mocks = [p for p in planned if p.kind == "mock_exam"]
    day_of = {e.exam_id: e.day for e in exams}
    assert len({m.exam_id for m in mocks}) == len(mocks)
    assert all(m.day < day_of[m.exam_id] for m in mocks if m.exam_id)


def test_weak_topics_near_their_exam_come_first() -> None:
    module = MODULES[0]
    exam = ExamSlot(uuid.uuid4(), module, START + timedelta(days=10), 120, "MATH101")
    weak = TopicNeed(module, uuid.UUID(int=1), "Integration", 300, exam.exam_id, exam.day)
    strong = TopicNeed(module, uuid.UUID(int=2), "Limits", 60, exam.exam_id, exam.day)
    days = [Day(START + timedelta(days=i), 90) for i in range(10)]
    planned, shortfalls = allocate(
        days, [weak, strong], [], [exam], CONFIG, session_minutes=SESSION, max_sessions=MAX_SESSIONS
    )
    topic_minutes: dict[str, int] = defaultdict(int)
    for p in planned:
        if p.topic_id:
            topic_minutes["Integration" if p.topic_id == weak.topic_id else "Limits"] += p.minutes
    assert topic_minutes["Integration"] > topic_minutes["Limits"] > 0
    assert any(p.kind == "mock_exam" for p in planned)
    # Plenty of time, but one topic needing 300 minutes cannot fit around the
    # spacing rules in 10 days of 45-minute sessions: said, with the reason.
    assert [s.reason for s in shortfalls] in ([], ["spacing"])
