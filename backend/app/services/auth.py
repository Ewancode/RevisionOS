"""Login, session validation, logout and password changes."""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import AuthConfig, RateLimit
from app.core.errors import AppError
from app.core.rate_limit import RateLimiter
from app.core.security import (
    burn_password_check,
    hash_password,
    hash_token,
    new_token,
    password_needs_rehash,
    token_matches,
    verify_password,
)
from app.models import AuthSession, User
from app.repositories.identity import AuditRepository, SessionRepository, UserRepository
from app.services.common import ClientInfo


def invalid_credentials() -> AppError:
    return AppError(
        "invalid_credentials", "That email and password combination is not recognised.", 401
    )


def not_authenticated() -> AppError:
    return AppError("not_authenticated", "Please sign in.", 401)


@dataclass(frozen=True)
class IssuedSession:
    user: User
    session_token: str
    csrf_token: str
    max_age_seconds: int


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: AuthSession


def validate_new_password(password: str, config: AuthConfig) -> None:
    if len(password) < config.password_min_length:
        raise AppError(
            "password_too_short",
            f"Use at least {config.password_min_length} characters.",
            422,
        )
    if len(password) > config.password_max_length:
        raise AppError("password_too_long", "That password is too long.", 422)


class AuthService:
    def __init__(
        self,
        db: AsyncSession,
        config: AuthConfig,
        limiter: RateLimiter,
        login_limit: RateLimit,
    ) -> None:
        self.db = db
        self.config = config
        self.limiter = limiter
        self.login_limit = login_limit
        self.users = UserRepository(db)
        self.sessions = SessionRepository(db)
        self.audit = AuditRepository(db)

    async def login(
        self,
        email: str,
        password: str,
        client: ClientInfo,
        previous_token: str | None,
    ) -> IssuedSession:
        email = email.strip().lower()
        keys = [self.limiter.key("login:email", email)]
        if client.ip:
            keys.append(self.limiter.key("login:ip", client.ip))
        for key in keys:
            result = await self.limiter.hit(key, self.login_limit)
            if not result.allowed:
                raise AppError(
                    "rate_limited",
                    f"Too many sign-in attempts. Try again in {result.retry_after_seconds} s.",
                    429,
                )

        user = await self.users.by_email(email)
        if user is None:
            burn_password_check(password)
        if user is None or not verify_password(user.password_hash, password):
            self.audit.record(
                "login_failed",
                user_id=user.id if user else None,
                ip=client.ip,
                user_agent=client.user_agent,
            )
            await self.db.commit()
            raise invalid_credentials()

        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

        now = utcnow()
        # Never carry a session across a login: whatever the browser held is revoked.
        if previous_token:
            previous = await self.sessions.by_token_hash(hash_token(previous_token))
            if previous is not None and previous.revoked_at is None:
                previous.revoked_at = now

        session_token, csrf_token = new_token(), new_token()
        lifetime = timedelta(days=self.config.session_absolute_days)
        self.db.add(
            AuthSession(
                user_id=user.id,
                token_hash=hash_token(session_token),
                csrf_token_hash=hash_token(csrf_token),
                last_seen_at=now,
                expires_at=now + lifetime,
                ip=client.ip,
                user_agent=client.user_agent,
            )
        )
        self.audit.record(
            "login_succeeded", user_id=user.id, ip=client.ip, user_agent=client.user_agent
        )
        await self.db.commit()
        await self.limiter.reset(*keys)
        return IssuedSession(user, session_token, csrf_token, int(lifetime.total_seconds()))

    async def authenticate(self, session_token: str | None) -> AuthContext:
        if not session_token:
            raise not_authenticated()
        session = await self.sessions.by_token_hash(hash_token(session_token))
        now = utcnow()
        idle_limit = timedelta(hours=self.config.session_idle_hours)
        if (
            session is None
            or session.revoked_at is not None
            or session.expires_at <= now
            or session.last_seen_at + idle_limit <= now
        ):
            raise not_authenticated()
        user = await self.users.by_id(session.user_id)
        if user is None:
            raise not_authenticated()

        touch_after = timedelta(seconds=self.config.session_touch_interval_seconds)
        if now - session.last_seen_at >= touch_after:
            session.last_seen_at = now
            await self.db.commit()
        return AuthContext(user, session)

    @staticmethod
    def csrf_valid(context: AuthContext, header_value: str | None) -> bool:
        return bool(header_value) and token_matches(
            header_value or "", context.session.csrf_token_hash
        )

    async def logout(self, context: AuthContext, client: ClientInfo) -> None:
        context.session.revoked_at = utcnow()
        self.audit.record(
            "logout", user_id=context.user.id, ip=client.ip, user_agent=client.user_agent
        )
        await self.db.commit()

    async def change_password(
        self, context: AuthContext, current: str, new: str, client: ClientInfo
    ) -> None:
        if not verify_password(context.user.password_hash, current):
            raise AppError("invalid_credentials", "Your current password is incorrect.", 401)
        validate_new_password(new, self.config)
        context.user.password_hash = hash_password(new)
        # Sign out everywhere else; this browser stays signed in.
        await self.sessions.revoke_all_for_user(
            context.user.id, utcnow(), except_id=context.session.id
        )
        self.audit.record(
            "password_changed",
            user_id=context.user.id,
            ip=client.ip,
            user_agent=client.user_agent,
        )
        await self.db.commit()
