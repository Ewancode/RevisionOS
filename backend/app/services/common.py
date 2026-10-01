from dataclasses import dataclass

from app.core.errors import AppError


@dataclass(frozen=True)
class ClientInfo:
    """Who is calling, for the audit log and rate limits."""

    ip: str | None
    user_agent: str | None


def not_found(kind: str) -> AppError:
    # Identical for "missing" and "someone else's", so ids cannot be probed.
    return AppError(f"{kind}_not_found", f"That {kind.replace('_', ' ')} does not exist.", 404)
