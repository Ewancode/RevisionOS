"""'I have 45 minutes': a session built from today's priorities, each part
with its reason (ARCHITECTURE.md section 11).

From the time you have:

1. due flashcards first, up to a share of the time (forgetting is the
   cheapest thing to prevent);
2. a short drill on your most pressing recurring mistake, if you have one;
3. the rest on the topic(s) the planner ranks highest today (weakness,
   need and exam urgency), split over two topics when there is a lot of it.

Every number in a reason is real; Claude may phrase it, but never computes it.
"""

import math
from dataclasses import dataclass, field
from typing import Any

from app.core.config import AppConfig
from app.learning.mistakes import MistakeGroup
from app.planner.context import PlannerContext, TopicInfo, needs, priority_now


@dataclass
class Block:
    kind: str  # flashcards | mistake_drill | topic
    title: str
    minutes: int
    reason: str
    # What the app should open: {"to": "review" | "mistakes" | "practice", ...}
    action: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionPlan:
    minutes: int
    blocks: list[Block]

    @property
    def summary(self) -> str:
        if not self.blocks:
            return "Nothing to schedule yet: add a module, upload materials and generate questions."
        parts = [f"{b.title} ({b.minutes} min)" for b in self.blocks]
        return f"{self.minutes} minutes: " + "; ".join(parts) + "."


def _round5(minutes: float) -> int:
    return max(5, int(round(minutes / 5) * 5))


def ranked_topics(ctx: PlannerContext, config: AppConfig) -> list[tuple[float, TopicInfo]]:
    days = max(
        1,
        (max((e.day for e in ctx.exams if e.day >= ctx.today), default=ctx.today) - ctx.today).days,
    )
    by_key = {n.key: n for n in needs(ctx, config, days)}
    ranked = [(priority_now(t, by_key[key], ctx, config), t) for key, t in ctx.topics.items()]
    return sorted(ranked, key=lambda pair: (-pair[0], pair[1].title))


def build(
    ctx: PlannerContext,
    minutes: int,
    due_cards: int,
    recurring: list[MistakeGroup],
    config: AppConfig,
) -> SessionPlan:
    settings = config.planner.session_builder
    left = minutes
    blocks: list[Block] = []

    if due_cards:
        wanted = math.ceil(due_cards * config.planner.reserve.flashcard_seconds / 60)
        share = _round5(min(wanted, minutes * settings.flashcard_share))
        if share <= left - 5 or not ctx.topics:
            share = min(share, left)
            blocks.append(
                Block(
                    "flashcards",
                    f"Review {due_cards} due flashcard{'s' if due_cards != 1 else ''}",
                    share,
                    f"{due_cards} card{'s are' if due_cards != 1 else ' is'} due; "
                    "reviewing now keeps "
                    "them from being forgotten",
                    {"to": "review"},
                )
            )
            left -= share

    if recurring and left >= settings.mistake_drill_minutes + settings.min_minutes:

        def pressing(group: MistakeGroup) -> tuple[int, int]:
            topic = ctx.topics.get((group.module_id, group.topic_id))
            days = (topic.exam.day - ctx.today).days if topic and topic.exam else 10_000
            return (days, -group.recent)

        group = min(recurring, key=pressing)
        blocks.append(
            Block(
                "mistake_drill",
                f"Drill {group.label.lower()}s in {group.topic_title}",
                settings.mistake_drill_minutes,
                f"{group.recent} {group.label.lower()}s in {group.topic_title} in the last 30 days",
                {"to": "mistakes", "module_id": str(group.module_id)},
            )
        )
        left -= settings.mistake_drill_minutes

    ranked = ranked_topics(ctx, config)
    if left >= 5 and ranked:
        if left > settings.split_above_minutes and len(ranked) > 1:
            first = _round5(left * 0.6)
            shares = [(ranked[0][1], first), (ranked[1][1], left - first)]
        else:
            shares = [(ranked[0][1], left)]
        for topic, share in shares:
            if share < 5:
                continue
            per_question = config.learning.daily_quiz.default_seconds_per_question
            blocks.append(
                Block(
                    "topic",
                    f"Practise {topic.title}",
                    share,
                    topic.factors(ctx.today, ctx.now),
                    {
                        "to": "practice",
                        "module_id": str(topic.module_id),
                        "topic_id": str(topic.topic_id) if topic.topic_id else None,
                        "questions": max(3, round(share * 60 / per_question)),
                    },
                )
            )
    return SessionPlan(minutes, blocks)


def recommend(
    ctx: PlannerContext,
    due_cards: int,
    recurring: list[MistakeGroup],
    config: AppConfig,
    limit: int = 3,
) -> list[Block]:
    """What to study next (SPEC section 71), best first, each with its reason.

    The same priorities as the planner: exams, weakness, recent mistakes,
    recency, coverage and topic importance. Many due flashcards come first,
    since forgetting is the cheapest thing to prevent.
    """
    per_question = config.learning.daily_quiz.default_seconds_per_question
    minutes = ctx.preferences.session_minutes
    found: list[Block] = []
    if due_cards >= config.planner.notifications.flashcards_due_threshold:
        found.append(
            Block(
                "flashcards",
                f"Review {due_cards} due flashcards",
                min(
                    math.ceil(due_cards * config.planner.reserve.flashcard_seconds / 60),
                    config.planner.reserve.flashcard_max_minutes,
                ),
                f"{due_cards} cards are due; reviewing now keeps them from being forgotten",
                {"to": "review"},
            )
        )
    patterns = {(g.module_id, g.topic_id): g for g in sorted(recurring, key=lambda g: g.recent)}
    for _, topic in ranked_topics(ctx, config):
        if len(found) >= limit:
            break
        reason = topic.factors(ctx.today, ctx.now)
        group = patterns.get(topic.key)
        if group is not None:
            reason += f" · recurring {group.label.lower()}"
        found.append(
            Block(
                "topic",
                topic.title,
                minutes,
                reason,
                {
                    "to": "practice",
                    "module_id": str(topic.module_id),
                    "topic_id": str(topic.topic_id) if topic.topic_id else None,
                    "questions": max(3, round(minutes * 60 / per_question)),
                },
            )
        )
    return found
