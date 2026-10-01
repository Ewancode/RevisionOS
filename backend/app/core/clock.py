"""Single source of 'now' so time-dependent rules can be tested."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
