import os

# Settings require DATABASE_URL. Unit tests never connect, so a placeholder is
# enough; database tests get a real URL from the `database_url` fixture.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1:1/unused")
os.environ["APP_ENV"] = "test"

from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from fastapi import FastAPI

from app.main import create_app


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A real PostgreSQL 16 + pgvector database.

    Uses TEST_DATABASE_URL when set (e.g. the compose `db` service); otherwise
    starts a throwaway container with Testcontainers. Skips — loudly — when
    neither is possible, because SQLite cannot stand in for pgvector.
    """
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        yield explicit
        return
    try:
        from testcontainers.community.postgres import PostgresContainer

        container = PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg")
        container.start()
    except Exception as exc:  # Docker missing or not running
        pytest.skip(f"no PostgreSQL available (set TEST_DATABASE_URL or start Docker): {exc}")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()
