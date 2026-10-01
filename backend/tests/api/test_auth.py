"""Login, sessions, CSRF, logout, password change (ARCHITECTURE.md section 12)."""

from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import get_config
from app.core.security import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from app.models import AuditLog, AuthSession
from app.services import auth as auth_service
from tests.support import PASSWORD, make_user, signed_in

pytestmark = pytest.mark.db

LOGIN = "/api/v1/auth/login"
SESSION = "/api/v1/auth/session"


def _set_cookie_headers(response: httpx.Response) -> dict[str, str]:
    return {h.split("=", 1)[0]: h for h in response.headers.get_list("set-cookie")}


async def test_login_sets_hardened_cookies(anon: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_user(db)
    response = await anon.post(LOGIN, json={"email": "EWAN@example.com", "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "ewan@example.com"
    assert body["settings"] == {"theme": "system", "accent_colour": "#4f46e5"}

    cookies = _set_cookie_headers(response)
    session_cookie = cookies[SESSION_COOKIE].lower()
    csrf_cookie = cookies[CSRF_COOKIE].lower()
    for header in (session_cookie, csrf_cookie):
        assert "secure" in header
        assert "samesite=lax" in header
        assert "path=/" in header
        assert "domain=" not in header
    assert "httponly" in session_cookie
    assert "httponly" not in csrf_cookie  # the SPA must be able to read it


async def test_tokens_are_stored_hashed(anon: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_user(db)
    await anon.post(LOGIN, json={"email": "ewan@example.com", "password": PASSWORD})
    token = anon.cookies[SESSION_COOKIE]
    stored = (await db.scalars(select(AuthSession))).one()
    assert token.encode() not in stored.token_hash
    assert len(stored.token_hash) == 32


async def test_wrong_password_and_unknown_email_look_identical(
    anon: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db)
    wrong = await anon.post(LOGIN, json={"email": "ewan@example.com", "password": "nope"})
    unknown = await anon.post(LOGIN, json={"email": "who@example.com", "password": "nope"})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert wrong.json()["error"]["code"] == "invalid_credentials"
    assert SESSION_COOKIE not in anon.cookies


async def test_login_attempts_are_audited(anon: httpx.AsyncClient, db: AsyncSession) -> None:
    user = await make_user(db)
    await anon.post(LOGIN, json={"email": "ewan@example.com", "password": "nope"})
    await anon.post(LOGIN, json={"email": "ewan@example.com", "password": PASSWORD})

    rows = (await db.scalars(select(AuditLog).order_by(AuditLog.id))).all()
    assert [(r.action, r.user_id, r.ip) for r in rows] == [
        ("login_failed", user.id, "203.0.113.10"),
        ("login_succeeded", user.id, "203.0.113.10"),
    ]


async def test_login_is_rate_limited_per_email(
    db_app: FastAPI, anon: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db)
    limit = get_config().platform.rate_limits.login.max_attempts
    for _ in range(limit):
        response = await anon.post(LOGIN, json={"email": "ewan@example.com", "password": "x"})
        assert response.status_code == 401

    # Even the right password is refused once the limit is hit...
    blocked = await anon.post(LOGIN, json={"email": "ewan@example.com", "password": PASSWORD})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"

    # ...including from a different IP, because the email is limited too.
    other_ip = httpx.ASGITransport(app=db_app, client=("192.0.2.99", 1))
    async with httpx.AsyncClient(transport=other_ip, base_url="https://test") as other:
        again = await other.post(LOGIN, json={"email": "ewan@example.com", "password": PASSWORD})
    assert again.status_code == 429


async def test_successful_login_resets_the_limit(anon: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_user(db)
    limit = get_config().platform.rate_limits.login.max_attempts
    for _ in range(limit - 1):
        await anon.post(LOGIN, json={"email": "ewan@example.com", "password": "x"})
    ok = await anon.post(LOGIN, json={"email": "ewan@example.com", "password": PASSWORD})
    assert ok.status_code == 200
    for _ in range(limit - 1):
        response = await anon.post(LOGIN, json={"email": "ewan@example.com", "password": "x"})
        assert response.status_code == 401


async def test_session_endpoint_requires_and_returns_the_session(
    db_app: FastAPI, anon: httpx.AsyncClient, db: AsyncSession
) -> None:
    assert (await anon.get(SESSION)).status_code == 401
    async with signed_in(db_app, await make_user(db)) as client:
        response = await client.get(SESSION)
    assert response.status_code == 200
    assert response.json()["user"]["display_name"] == "Ewan"


async def test_unsafe_requests_need_the_csrf_token(db_app: FastAPI, db: AsyncSession) -> None:
    async with signed_in(db_app, await make_user(db)) as client:
        body = {"label": "2026/27", "start_date": "2026-09-21", "end_date": "2027-06-11"}

        del client.headers[CSRF_HEADER]
        missing = await client.post("/api/v1/years", json=body)
        client.headers[CSRF_HEADER] = "forged-token"
        forged = await client.post("/api/v1/years", json=body)
        client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]
        ok = await client.post("/api/v1/years", json=body)

    assert missing.status_code == forged.status_code == 403
    assert missing.json()["error"]["code"] == "csrf_failed"
    assert ok.status_code == 201


async def test_logout_revokes_the_session(db_app: FastAPI, db: AsyncSession) -> None:
    async with signed_in(db_app, await make_user(db)) as client:
        token = client.cookies[SESSION_COOKIE]
        assert (await client.post("/api/v1/auth/logout")).status_code == 204
        assert SESSION_COOKIE not in client.cookies

        # Replaying the old token no longer works.
        client.cookies.set(SESSION_COOKIE, token)
        assert (await client.get(SESSION)).status_code == 401


async def test_login_revokes_the_previous_session(db_app: FastAPI, db: AsyncSession) -> None:
    user = await make_user(db)
    async with signed_in(db_app, user) as client:
        old = client.cookies[SESSION_COOKIE]
        await client.post(LOGIN, json={"email": user.email, "password": PASSWORD})
        assert client.cookies[SESSION_COOKIE] != old
        client.cookies.set(SESSION_COOKIE, old)
        assert (await client.get(SESSION)).status_code == 401


@pytest.mark.parametrize(
    ("advance", "expected"),
    [
        (timedelta(hours=1), 200),
        (timedelta(hours=get_config().platform.auth.session_idle_hours, seconds=1), 401),
    ],
)
async def test_idle_sessions_expire(
    db_app: FastAPI,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    advance: timedelta,
    expected: int,
) -> None:
    async with signed_in(db_app, await make_user(db)) as client:
        later = utcnow() + advance
        monkeypatch.setattr(auth_service, "utcnow", lambda: later)
        assert (await client.get(SESSION)).status_code == expected


async def test_active_sessions_still_end_at_the_absolute_limit(
    db_app: FastAPI, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = get_config().platform.auth
    async with signed_in(db_app, await make_user(db)) as client:
        start = utcnow()
        # Use the session every 3 days, so it is never idle for long...
        for day in range(3, config.session_absolute_days, 3):
            moment = start + timedelta(days=day)
            monkeypatch.setattr(auth_service, "utcnow", lambda m=moment: m)
            assert (await client.get(SESSION)).status_code == 200
        # ...and it still ends at the absolute lifetime.
        end = start + timedelta(days=config.session_absolute_days, seconds=1)
        monkeypatch.setattr(auth_service, "utcnow", lambda: end)
        assert (await client.get(SESSION)).status_code == 401


async def test_password_change_signs_out_other_sessions(db_app: FastAPI, db: AsyncSession) -> None:
    user = await make_user(db)
    new_password = "a much longer new passphrase"
    async with signed_in(db_app, user) as a, signed_in(db_app, user, ip="198.51.100.8") as b:
        response = await a.post(
            "/api/v1/auth/password",
            json={"current_password": PASSWORD, "new_password": new_password},
        )
        assert response.status_code == 204
        assert (await a.get(SESSION)).status_code == 200  # this browser stays in
        assert (await b.get(SESSION)).status_code == 401  # others are signed out

        relogin = await b.post(LOGIN, json={"email": user.email, "password": new_password})
        assert relogin.status_code == 200


@pytest.mark.parametrize(
    ("current", "new", "status", "code"),
    [
        ("wrong", "a much longer new passphrase", 401, "invalid_credentials"),
        (PASSWORD, "short", 422, "password_too_short"),
    ],
)
async def test_password_change_rejections(
    db_app: FastAPI, db: AsyncSession, current: str, new: str, status: int, code: str
) -> None:
    async with signed_in(db_app, await make_user(db)) as client:
        response = await client.post(
            "/api/v1/auth/password", json={"current_password": current, "new_password": new}
        )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


async def test_settings_update(db_app: FastAPI, db: AsyncSession) -> None:
    async with signed_in(db_app, await make_user(db)) as client:
        response = await client.patch(
            "/api/v1/settings",
            json={"theme": "dark", "accent_colour": "#0EA5E9", "display_name": "  E. T.  "},
        )
        assert response.status_code == 200
        assert response.json()["settings"] == {"theme": "dark", "accent_colour": "#0ea5e9"}
        assert response.json()["user"]["display_name"] == "E. T."

        bad = await client.patch("/api/v1/settings", json={"accent_colour": "red"})
        assert bad.status_code == 422
        null = await client.patch("/api/v1/settings", json={"theme": None})
        assert null.status_code == 422
