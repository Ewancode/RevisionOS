"""Request-scoped dependencies: database, config, the signed-in user and CSRF.

Every router except health and login is mounted with `require_auth` and
`require_csrf`, so a new endpoint is protected unless it is deliberately
placed on the public router.
"""

from typing import Annotated, Any, Literal

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig, get_config
from app.core.errors import AppError
from app.core.rate_limit import RateLimiter
from app.core.security import CSRF_HEADER, SESSION_COOKIE
from app.db.session import get_session
from app.models import User
from app.services.auth import AuthContext, AuthService
from app.services.common import ClientInfo

DbSession = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[AppConfig, Depends(get_config)]

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
MAX_USER_AGENT = 512


def client_info(request: Request) -> ClientInfo:
    user_agent = request.headers.get("user-agent")
    return ClientInfo(
        ip=request.client.host if request.client else None,
        user_agent=user_agent[:MAX_USER_AGENT] if user_agent else None,
    )


Client = Annotated[ClientInfo, Depends(client_info)]


def auth_service(request: Request, db: DbSession, config: Config) -> AuthService:
    return AuthService(
        db,
        config.platform.auth,
        RateLimiter(request.app.state.redis),
        config.platform.rate_limits.login,
    )


Auth = Annotated[AuthService, Depends(auth_service)]


async def require_auth(request: Request, auth: Auth) -> AuthContext:
    return await auth.authenticate(request.cookies.get(SESSION_COOKIE))


AuthCtx = Annotated[AuthContext, Depends(require_auth)]


async def require_csrf(request: Request, context: AuthCtx) -> None:
    """Unsafe methods must echo the session's CSRF token in a header. A
    cross-site page can make the browser send our cookies, but cannot read
    the CSRF cookie to copy it into the header."""
    if request.method in SAFE_METHODS:
        return
    if not AuthService.csrf_valid(context, request.headers.get(CSRF_HEADER)):
        raise AppError(
            "csrf_failed", "Your session token is missing or stale. Reload the page.", 403
        )


def current_user(context: AuthCtx) -> User:
    return context.user


CurrentUser = Annotated[User, Depends(current_user)]

LimitScope = Literal["ai", "uploads", "push_test", "exports"]


def rate_limited(scope: LimitScope) -> Any:
    """A per-account rate limit (platform.yaml rate_limits), as a route
    dependency: ``dependencies=[rate_limited("ai")]``."""

    async def check(request: Request, user: CurrentUser, config: Config) -> None:
        limiter = RateLimiter(request.app.state.redis)
        result = await limiter.hit(
            limiter.key(scope, str(user.id)), getattr(config.platform.rate_limits, scope)
        )
        if not result.allowed:
            raise AppError(
                "rate_limited",
                f"Too many requests just now. Try again in {result.retry_after_seconds} s.",
                429,
            )

    check.rate_limit_scope = scope  # type: ignore[attr-defined]  # read by the tests
    return Depends(check)


PROTECTED = [Depends(require_auth), Depends(require_csrf)]
