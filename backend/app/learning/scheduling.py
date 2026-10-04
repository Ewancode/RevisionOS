"""Flashcard scheduling with FSRS (ARCHITECTURE.md section 10, "Spaced repetition").

Again, Hard, Good and Easy map to ratings 1-4. The fsrs library holds the
algorithm; this module maps between its Card and our flashcards row, and
records every review as a fact.
"""

from datetime import datetime, timedelta

from fsrs import Card, Rating, Scheduler, State

from app.core.config import SpacedRepetitionConfig
from app.models import Flashcard, FlashcardReview

DAY_SECONDS = 86_400


def scheduler(config: SpacedRepetitionConfig, *, fuzz: bool | None = None) -> Scheduler:
    return Scheduler(
        desired_retention=config.target_retention,
        learning_steps=tuple(timedelta(minutes=m) for m in config.learning_steps_minutes),
        relearning_steps=tuple(timedelta(minutes=m) for m in config.relearning_steps_minutes),
        maximum_interval=config.maximum_interval_days,
        enable_fuzzing=config.fuzz if fuzz is None else fuzz,
    )


def to_card(row: Flashcard) -> Card:
    return Card(
        state=State(row.fsrs_state),
        step=row.fsrs_step,
        stability=row.stability,
        difficulty=row.fsrs_difficulty,
        due=row.due,
        last_review=row.last_review,
    )


def retrievability(row: Flashcard, now: datetime, config: SpacedRepetitionConfig) -> float | None:
    """Chance of recalling the card now (None if never reviewed)."""
    if row.last_review is None or row.stability is None:
        return None
    return float(scheduler(config).get_card_retrievability(to_card(row), now))


def preview(row: Flashcard, now: datetime, config: SpacedRepetitionConfig) -> dict[int, float]:
    """Days until the card would be due again, for each rating (no fuzz)."""
    plain = scheduler(config, fuzz=False)
    return {
        int(rating): (
            plain.review_card(to_card(row), rating, review_datetime=now)[0].due - now
        ).total_seconds()
        / DAY_SECONDS
        for rating in Rating
    }


def review(
    row: Flashcard,
    rating: int,
    now: datetime,
    config: SpacedRepetitionConfig,
    duration_ms: int | None = None,
) -> FlashcardReview:
    """Apply a review to the card row and return the review fact to store."""
    before_state, before_review = row.fsrs_state, row.last_review
    card, _ = scheduler(config).review_card(to_card(row), Rating(rating), review_datetime=now)
    if before_state == State.Review and rating == Rating.Again:
        row.lapses += 1
    row.reps += 1
    row.fsrs_state = int(card.state)
    row.fsrs_step = card.step
    row.stability, row.fsrs_difficulty = card.stability, card.difficulty
    row.due, row.last_review = card.due, card.last_review
    return FlashcardReview(
        user_id=row.user_id,
        flashcard_id=row.id,
        rating=rating,
        reviewed_at=now,
        state_before=before_state,
        elapsed_days=(now - before_review).total_seconds() / DAY_SECONDS if before_review else None,
        stability=card.stability,
        difficulty=card.difficulty,
        scheduled_days=(card.due - now).total_seconds() / DAY_SECONDS,
        duration_ms=duration_ms,
    )
