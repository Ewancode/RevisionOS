"""Migrations run up, down and up again against real PostgreSQL + pgvector.

Synchronous on purpose: Alembic's env.py drives its own event loop.
"""

import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.settings import BACKEND_ROOT
from app.db.session import create_engine

pytestmark = pytest.mark.db


def _alembic(database_url: str) -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = database_url
    return cfg


def _has_pgvector(database_url: str) -> bool:
    async def query() -> bool:
        engine = create_engine(database_url)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                )
                return result.scalar() is not None
        finally:
            await engine.dispose()

    return asyncio.run(query())


def test_upgrade_downgrade_round_trip(database_url: str) -> None:
    cfg = _alembic(database_url)

    command.upgrade(cfg, "head")
    assert _has_pgvector(database_url)

    command.downgrade(cfg, "base")
    assert not _has_pgvector(database_url)

    command.upgrade(cfg, "head")
    assert _has_pgvector(database_url)
