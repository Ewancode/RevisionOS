"""Migrations run up, down and up again against real PostgreSQL + pgvector,
in a database of their own so they never disturb the API tests.

Synchronous on purpose: Alembic's env.py drives its own event loop.
"""

import asyncio

import pytest
from alembic import command
from sqlalchemy import text

from app.db.session import create_engine
from tests.support import alembic_config, create_database

pytestmark = pytest.mark.db


def _query(database_url: str, sql: str) -> list[str]:
    async def run() -> list[str]:
        engine = create_engine(database_url)
        try:
            async with engine.connect() as conn:
                return [str(row[0]) for row in await conn.execute(text(sql))]
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _state(url: str) -> tuple[list[str], list[str], list[str]]:
    extensions = _query(url, "SELECT extname FROM pg_extension WHERE extname = 'vector'")
    tables = _query(
        url,
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
        "AND tablename <> 'alembic_version' ORDER BY 1",
    )
    enums = _query(url, "SELECT typname FROM pg_type WHERE typtype = 'e' ORDER BY 1")
    return extensions, tables, enums


def test_upgrade_downgrade_round_trip(database_url: str) -> None:
    url = create_database(database_url, "migrations")
    cfg = alembic_config(url)

    command.upgrade(cfg, "head")
    extensions, tables, enums = _state(url)
    assert extensions == ["vector"]
    assert {"users", "auth_sessions", "academic_years", "modules", "topics"} <= set(tables)
    assert enums == ["module_status", "theme"]

    # Fully reversible: nothing is left behind, including enum types.
    command.downgrade(cfg, "base")
    assert _state(url) == ([], [], [])

    command.upgrade(cfg, "head")
    assert _state(url) == (extensions, tables, enums)
