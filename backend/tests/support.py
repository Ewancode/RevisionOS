"""Helpers shared by tests: databases, accounts and signed-in clients."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_config
from app.core.security import CSRF_COOKIE, CSRF_HEADER
from app.core.settings import BACKEND_ROOT
from app.models import User
from app.services.users import create_user

# Secure cookies are only sent over https, so tests talk "https" to the app.
BASE_URL = "https://test"
PASSWORD = "correct horse battery staple"


def create_database(server_url: str, name: str) -> str:
    """Create a fresh, uniquely named database on the server; return its URL."""
    db_name = f"{name}_{uuid.uuid4().hex[:8]}"

    async def run() -> None:
        engine = create_async_engine(server_url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        finally:
            await engine.dispose()

    asyncio.run(run())
    return make_url(server_url).set(database=db_name).render_as_string(hide_password=False)


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = database_url
    return cfg


def migrate(database_url: str, revision: str) -> None:
    command.upgrade(alembic_config(database_url), revision)


async def make_user(db: AsyncSession, email: str = "ewan@example.com", name: str = "Ewan") -> User:
    return await create_user(
        db, get_config().platform.auth, email=email, display_name=name, password=PASSWORD
    )


@asynccontextmanager
async def signed_in(
    app: FastAPI, user: User, ip: str = "198.51.100.7"
) -> AsyncIterator[httpx.AsyncClient]:
    """A client with a live session and the CSRF header set, as the SPA does."""
    transport = httpx.ASGITransport(app=app, client=(ip, 50000))
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        response = await client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
        client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]
        yield client
