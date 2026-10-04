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
    assert {
        "users",
        "auth_sessions",
        "academic_years",
        "modules",
        "topics",
        "documents",
        "document_pages",
        "ai_interactions",
        "ai_usage",
        "chunks",
        "conversations",
        "messages",
        "pending_actions",
        "drafts",
        "materials",
        "material_versions",
        "questions",
        "flashcards",
        "quizzes",
        "quiz_items",
        "quiz_attempts",
        "question_attempts",
        "flashcard_reviews",
        "topic_mastery",
        "learning_profile_snapshots",
        "exams",
        "exam_topics",
        "availability_rules",
        "availability_overrides",
        "revision_plans",
        "study_sessions",
        "notifications",
    } <= set(tables)
    assert enums == [
        "ai_interaction_status",
        "attempt_mode",
        "attempt_status",
        "confidence",
        "content_origin",
        "document_status",
        "draft_kind",
        "draft_status",
        "extraction_method",
        "marked_by",
        "material_kind",
        "message_role",
        "message_status",
        "module_status",
        "pending_action_kind",
        "pending_action_status",
        "question_difficulty",
        "question_status",
        "question_type",
        "quiz_kind",
        "session_kind",
        "session_status",
        "source_tier",
        "study_material_kind",
        "theme",
    ]

    # Fully reversible: nothing is left behind, including enum types.
    command.downgrade(cfg, "base")
    assert _state(url) == ([], [], [])

    command.upgrade(cfg, "head")
    assert _state(url) == (extensions, tables, enums)
