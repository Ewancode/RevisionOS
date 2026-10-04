import os

# Settings require DATABASE_URL. Unit tests never connect, so a placeholder is
# enough; database tests get a real URL from the `database_url` fixture.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1:1/unused")
os.environ["APP_ENV"] = "test"

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.ai.client import ClaudeClient
from app.core.config import get_config
from app.db.session import create_engine, create_session_factory
from app.ingestion.pipeline import Deps
from app.main import create_app
from app.retrieval.embeddings import HashingProvider
from app.storage import LocalStorage
from tests.fakes import FakeAnthropic, RecordingQueue
from tests.support import BASE_URL, create_database, migrate

# Tables emptied between database tests, children first.
TABLES = (
    "flashcard_reviews",
    "topic_mastery",
    "learning_profile_snapshots",
    "question_attempts",
    "quiz_attempts",
    "quiz_items",
    "quizzes",
    "questions",
    "flashcards",
    "material_versions",
    "materials",
    "drafts",
    "pending_actions",
    "messages",
    "conversations",
    "chunks",
    "ai_usage",
    "ai_interactions",
    "document_pages",
    "documents",
    "topics",
    "modules",
    "academic_years",
    "audit_log",
    "auth_sessions",
    "user_settings",
    "users",
)


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as c:
        yield c


# --- real database -----------------------------------------------------------


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A PostgreSQL 16 + pgvector *server*.

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


@pytest.fixture(scope="session")
def app_database_url(database_url: str) -> str:
    """A dedicated database migrated to head, shared by the API tests."""
    url = create_database(database_url, "api_tests")
    migrate(url, "head")
    return url


@pytest.fixture(scope="session")
async def engine(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(app_database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with create_session_factory(engine)() as session:
        yield session
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))


@pytest.fixture
def fake_claude() -> FakeAnthropic:
    return FakeAnthropic()


@pytest.fixture
def queue() -> RecordingQueue:
    return RecordingQueue()


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


@pytest.fixture
def claude(fake_claude: FakeAnthropic) -> ClaudeClient:
    return ClaudeClient(fake_claude, get_config().ai)


@pytest.fixture
def db_app(
    engine: AsyncEngine,
    db: AsyncSession,
    storage: LocalStorage,
    queue: RecordingQueue,
    claude: ClaudeClient,
) -> FastAPI:
    """The app wired to the test database, a fresh in-memory Redis, local
    storage in a temp dir, a recording job queue and a fake Claude.

    `db` is requested so tables are truncated after each test.
    """
    app = create_app()
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.redis = FakeAsyncRedis()
    app.state.storage = storage
    app.state.jobs = queue
    app.state.claude = claude
    app.state.embedder = HashingProvider(get_config().retrieval.embeddings.dimensions)
    return app


@pytest.fixture
def deps(engine: AsyncEngine, storage: LocalStorage, claude: ClaudeClient) -> Deps:
    """What the worker passes to the pipeline, for running jobs in-process."""
    return Deps(
        create_session_factory(engine),
        storage,
        claude,
        get_config(),
        HashingProvider(get_config().retrieval.embeddings.dimensions),
    )


@pytest.fixture
async def anon(db_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=db_app, client=("203.0.113.10", 50000))
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as c:
        yield c
