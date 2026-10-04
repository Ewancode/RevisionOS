"""Single source of 'now' so time-dependent rules can be tested."""

from datetime import UTC, datetime

# Set by tests (e.g. the simulated learner) to move through days.
_frozen: datetime | None = None


def utcnow() -> datetime:
    return _frozen if _frozen is not None else datetime.now(UTC)


def freeze(at: datetime | None) -> None:
    """Fix 'now' at `at` (None returns to the real clock). Tests only."""
    global _frozen
    _frozen = at
