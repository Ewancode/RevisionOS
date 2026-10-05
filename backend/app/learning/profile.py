"""The learning profile (SPEC 28; ARCHITECTURE.md section 10, "Learning profile").

Measured statistics only: accuracy by question type, under exam conditions
versus not, how often each kind of mistake occurs, hint use, and the gap
between flashcard recall and applying the same material in questions. Claude
writes a short weekly summary that must cite these numbers and may not make
personality claims. Generation prompts receive a compact form of it.
"""

import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig
from app.learning.mistakes import CATEGORY_LABELS
from app.models import FlashcardReview, Question, QuestionAttempt, QuizAttempt

RECENT_DAYS = 30


async def metrics(
    db: AsyncSession, user_id: uuid.UUID, config: AppConfig, now: datetime
) -> dict[str, Any]:
    correct_at = config.practice.marking.correct_at
    rows = (
        await db.execute(
            # Columns, not ORM objects (Phase 12 performance tests).
            select(
                QuestionAttempt.score,
                QuestionAttempt.hints_used,
                QuestionAttempt.mistake_category,
                QuestionAttempt.marked_at,
                Question.type,
                QuizAttempt.mode,
            )
            .join(Question, Question.id == QuestionAttempt.question_id)
            .join(QuizAttempt, QuizAttempt.id == QuestionAttempt.quiz_attempt_id)
            .where(QuestionAttempt.user_id == user_id, QuestionAttempt.score.is_not(None))
            .order_by(QuestionAttempt.marked_at.desc())
        )
    ).all()
    by_type: dict[str, list[float]] = defaultdict(list)
    by_mode: dict[str, list[float]] = defaultdict(list)
    hints: list[int] = []
    errors: list[str] = []
    recent_days: set[date] = set()
    for raw_score, hints_used, mistake_category, marked_at, question_type, mode in rows:
        score = float(raw_score or 0.0)
        by_type[question_type].append(score)
        by_mode[mode].append(score)
        hints.append(hints_used)
        if mistake_category and score < correct_at:
            errors.append(str(mistake_category))
        if marked_at and marked_at >= now - timedelta(days=RECENT_DAYS):
            recent_days.add(marked_at.date())

    def summary(scores: list[float]) -> dict[str, float | int]:
        return {"answered": len(scores), "accuracy": round(sum(scores) / len(scores), 3)}

    recent_errors = errors[: config.learning.profile.recent_errors]
    reviews = (
        await db.scalars(
            select(FlashcardReview.rating).where(
                FlashcardReview.user_id == user_id,
                FlashcardReview.reviewed_at >= now - timedelta(days=RECENT_DAYS),
            )
        )
    ).all()
    recall = round(sum(1 for r in reviews if r >= 3) / len(reviews), 3) if reviews else None
    all_scores = [s for scores in by_type.values() for s in scores]
    application = round(sum(all_scores) / len(all_scores), 3) if all_scores else None
    return {
        "answered": len(all_scores),
        "accuracy": application,
        "by_type": {t: summary(s) for t, s in sorted(by_type.items())},
        "exam_conditions": summary(by_mode["exam"]) if by_mode.get("exam") else None,
        "untimed": summary(by_mode["normal"]) if by_mode.get("normal") else None,
        "recent_errors": {
            "considered": len(recent_errors),
            "by_category": dict(Counter(recent_errors).most_common()),
        },
        "hints_per_answer": round(sum(hints) / len(hints), 2) if hints else 0.0,
        "flashcards": {"reviews_30d": len(reviews), "recall_rate": recall},
        "recall_minus_application": round(recall - application, 3)
        if recall is not None and application is not None
        else None,
        "active_days_30d": len(recent_days),
    }


def prompt_hint(data: dict[str, Any]) -> str:
    """A compact, factual line for generation prompts, e.g. "3 of the last
    10 mistakes were sign errors; include sign-sensitive steps"."""
    parts = []
    errors = data.get("recent_errors") or {}
    considered = errors.get("considered") or 0
    for category, count in list((errors.get("by_category") or {}).items())[:2]:
        if count >= 2:
            label = CATEGORY_LABELS.get(category, category).lower()
            parts.append(f"{count} of the last {considered} mistakes were {label}s")
    weak = sorted(
        (
            (stats["accuracy"], t)
            for t, stats in (data.get("by_type") or {}).items()
            if stats["answered"] >= 3
        )
    )
    if weak and weak[0][0] < 0.6:
        parts.append(
            f"accuracy on {weak[0][1].replace('_', ' ')} questions is {round(weak[0][0] * 100)}%"
        )
    if not parts:
        return ""
    return (
        "Measured from the student's recent answers: " + "; ".join(parts) + ". Where it fits the "
        "material, include questions that exercise these weaknesses."
    )


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())
