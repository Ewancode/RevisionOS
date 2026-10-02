"""Helpers shared by tests: databases, accounts and signed-in clients."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

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
from app.ingestion.pipeline import Deps, process_document
from app.models import User
from app.services.users import create_user
from tests.fakes import RecordingQueue

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


# --- course data through the API --------------------------------------------------


async def create_module(client: httpx.AsyncClient, code: str = "MATH260") -> dict[str, Any]:
    years = (await client.get("/api/v1/years")).json()
    if years:
        year = years[0]
    else:
        year = (
            await client.post(
                "/api/v1/years",
                json={"label": "2026/27", "start_date": "2026-09-21", "end_date": "2027-06-11"},
            )
        ).json()
    response = await client.post(
        "/api/v1/modules",
        json={"academic_year_id": year["id"], "code": code, "title": "Financial Maths"},
    )
    return dict(response.json())


async def ingest(
    client: httpx.AsyncClient,
    deps: Deps,
    queue: RecordingQueue,
    module_id: str,
    path: Path,
    name: str,
    **params: Any,
) -> str:
    query = {
        "module_id": module_id,
        "filename": name,
        "source_tier": "university",
        "material_kind": "lecture",
        **params,
    }
    response = await client.post("/api/v1/documents", params=query, content=path.read_bytes())
    assert response.status_code == 202, response.text
    doc_id = str(response.json()["id"])
    while queue.jobs:
        _, args = queue.jobs.pop(0)
        await process_document(deps, uuid.UUID(args[0]))
    return doc_id
