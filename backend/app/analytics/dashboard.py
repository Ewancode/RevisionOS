"""Which of Today's panels come first (SPEC 4; ADR 15 deferred this to
Phase 11). Deterministic, no AI: each panel scores its place in the usual
order, plus a boost when something about it is pressing; ties keep the usual
order. Each moved panel says why.
"""

from dataclasses import dataclass

from app.core.config import DashboardConfig


@dataclass(frozen=True)
class Pressing:
    """What is pressing right now."""

    exam_days: int | None = None  # the nearest exam, in days
    exam_title: str = ""
    quiz_not_done: bool = False
    cards_due: int = 0
    cards_threshold: int = 10
    recurring_mistakes: int = 0


@dataclass(frozen=True)
class Panel:
    key: str
    reason: str | None


def rank(config: DashboardConfig, pressing: Pressing) -> list[Panel]:
    n = len(config.order)
    score = {key: float(n - i) for i, key in enumerate(config.order)}
    reasons: dict[str, str] = {}
    boosts = config.boosts

    def boost(key: str, by: float, reason: str) -> None:
        score[key] += by
        reasons[key] = reason

    days = pressing.exam_days
    if days is not None and days <= config.exam_soon_days:
        when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
        boost("exams", boosts.exam_soon, f"{pressing.exam_title} is {when}")
        boost("todays_revision", boosts.exam_soon, f"{pressing.exam_title} is {when}")
    if pressing.quiz_not_done:
        boost("daily_quiz", boosts.quiz_not_done, "Today's quiz is not done yet")
    if pressing.cards_due >= pressing.cards_threshold:
        boost("flashcards", boosts.cards_due, f"{pressing.cards_due} flashcards are due")
    if pressing.recurring_mistakes:
        boost(
            "mistakes",
            boosts.recurring_mistakes,
            f"{pressing.recurring_mistakes} recurring mistake"
            + ("s" if pressing.recurring_mistakes != 1 else ""),
        )
    usual = {key: i for i, key in enumerate(config.order)}
    ordered = sorted(config.order, key=lambda k: (-score[k], usual[k]))
    return [Panel(key, reasons.get(key)) for key in ordered]
