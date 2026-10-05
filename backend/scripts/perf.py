"""Performance tests (ARCHITECTURE.md section 13; Phase 12).

Usage: ``make perf`` (or ``python -m scripts.perf``), inside the api container.

1. Creates a separate database, ``revision_os_perf``, migrates it and seeds
   a heavy year of use for one account (sizes in platform.yaml
   ``performance.seed``). Done once; later runs reuse it.
2. Times the requests each page makes, in the server process (no network),
   after a warm-up: ``samples`` requests each, reporting p50 and p95 against
   the targets in platform.yaml ``performance.targets_ms``.
3. Runs ``concurrency`` clients at once for ``burst_seconds``: no errors,
   and p95 within ``burst_slowdown`` times the page target.

Exits non-zero if any target is missed. Your own database is never touched.
"""

import argparse
import asyncio
import math
import os
import random
import statistics
import subprocess
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import asyncpg
import httpx
from redis.asyncio import Redis
from sqlalchemy import insert, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import create_client
from app.core.config import AppConfig, get_config
from app.core.logging import configure_logging
from app.core.runtime import freeze_heap
from app.core.security import CSRF_COOKIE, CSRF_HEADER
from app.core.settings import get_settings
from app.db.session import create_engine, create_session_factory
from app.learning.mastery import recompute
from app.main import create_app
from app.models import (
    AcademicYear,
    Chunk,
    CodingExercise,
    Document,
    DocumentPage,
    Exam,
    Flashcard,
    FlashcardReview,
    Material,
    MaterialVersion,
    Module,
    Question,
    QuestionAttempt,
    Quiz,
    QuizAttempt,
    QuizItem,
    Topic,
    User,
)
from app.models.retrieval import EMBEDDING_DIMENSIONS
from app.retrieval.embeddings import create_provider
from app.services.users import create_user
from app.storage import create_storage

PERF_DB = "revision_os_perf"
EMAIL = "perf@revision-os.test"
# A throwaway account in a local, seeded-only database.
PASSWORD = "perf-only local seeded database"  # noqa: S105 - not a real credential
WORDS = [
    "series",
    "convergence",
    "ratio",
    "test",
    "integral",
    "derivative",
    "limit",
    "continuity",
    "matrix",
    "eigenvalue",
    "vector",
    "probability",
    "distribution",
    "variance",
    "expectation",
    "regression",
    "hypothesis",
    "estimator",
    "likelihood",
    "theorem",
    "proof",
    "lemma",
    "function",
    "sequence",
    "bound",
    "inequality",
    "partial",
    "fraction",
    "substitution",
    "differential",
    "equation",
    "volatility",
    "portfolio",
    "return",
    "option",
    "pricing",
    "martingale",
    "stochastic",
]


def sentence(rng: random.Random, n: int = 14) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(n)).capitalize() + "."


def perf_url() -> str:
    url = make_url(get_settings().database_url.get_secret_value())
    return url.set(database=PERF_DB).render_as_string(hide_password=False)


async def ensure_database() -> bool:
    """Create and migrate the perf database. True if it was just created."""
    url = make_url(get_settings().database_url.get_secret_value())
    conn = await asyncpg.connect(
        user=url.username,
        password=url.password,
        host=url.host,
        port=url.port or 5432,
        database="postgres",
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", PERF_DB)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{PERF_DB}"')
    finally:
        await conn.close()
    await asyncio.to_thread(
        subprocess.run,
        ["alembic", "upgrade", "head"],
        check=True,
        env={**os.environ, "DATABASE_URL": perf_url()},
    )
    return not exists


async def bulk(db: AsyncSession, model: Any, rows: list[dict[str, Any]], size: int = 2000) -> None:
    for i in range(0, len(rows), size):
        await db.execute(insert(model), rows[i : i + size])


async def seed(db: AsyncSession, config: AppConfig) -> None:
    if await db.scalar(select(User.id).where(User.email == EMAIL)):
        print("perf database already seeded")
        return
    s = config.platform.performance.seed
    rng = random.Random(12)  # noqa: S311 - seeded test data, not security
    now = datetime.now(UTC)
    started = time.perf_counter()
    user = await create_user(
        db, config.platform.auth, email=EMAIL, display_name="Perf", password=PASSWORD
    )
    uid = user.id
    year = AcademicYear(
        id=uuid.uuid4(),
        user_id=uid,
        label="2026/27",
        start_date=date(2026, 9, 21),
        end_date=date(2027, 6, 11),
        is_current=True,
    )
    db.add(year)
    await db.flush()

    modules: list[uuid.UUID] = []
    topics: dict[uuid.UUID, list[uuid.UUID]] = {}
    for m in range(s.modules):
        module_id = uuid.uuid4()
        modules.append(module_id)
        db.add(
            Module(
                id=module_id,
                user_id=uid,
                academic_year_id=year.id,
                code=f"MATH{101 + m}",
                title=f"Module {m + 1}",
            )
        )
        await db.flush()
        topics[module_id] = []
        for t in range(s.topics_per_module):
            topic_id = uuid.uuid4()
            topics[module_id].append(topic_id)
            db.add(
                Topic(
                    id=topic_id,
                    user_id=uid,
                    module_id=module_id,
                    title=f"Topic {t + 1}",
                    position=t,
                )
            )
        db.add(
            Exam(
                id=uuid.uuid4(),
                user_id=uid,
                module_id=module_id,
                title="Final exam",
                starts_at=now + timedelta(days=10 + 7 * m),
                duration_minutes=120,
            )
        )
    await db.flush()
    print(f"  structure: {len(modules)} modules, {sum(len(t) for t in topics.values())} topics")

    # Documents, pages and searchable chunks with embeddings.
    docs, pages, chunks = [], [], []
    for module_id in modules:
        for d in range(s.documents_per_module):
            doc_id = uuid.uuid4()
            docs.append(
                {
                    "id": doc_id,
                    "user_id": uid,
                    "module_id": module_id,
                    "original_filename": f"week{d + 1}.pdf",
                    "storage_key": f"users/{uid}/documents/{doc_id}/original",
                    "mime": "application/pdf",
                    "size_bytes": 1_000_000,
                    "sha256": uuid.uuid4().bytes * 2,
                    "source_tier": "university",
                    "material_kind": "lecture",
                    "status": "ready",
                    "page_count": s.pages_per_document,
                }
            )
            for p in range(1, s.pages_per_document + 1):
                text = " ".join(sentence(rng) for _ in range(12))
                pages.append(
                    {
                        "document_id": doc_id,
                        "page_no": p,
                        "markdown": text,
                        "extraction_method": "text",
                    }
                )
                for c in range(s.chunks_per_page):
                    vector = [rng.gauss(0, 1) for _ in range(EMBEDDING_DIMENSIONS)]
                    norm = math.sqrt(sum(v * v for v in vector))
                    chunks.append(
                        {
                            "user_id": uid,
                            "document_id": doc_id,
                            "module_id": module_id,
                            "topic_id": rng.choice(topics[module_id]),
                            "source_tier": "university",
                            "page_no": p,
                            "position": c,
                            "content": text[c * 300 : c * 300 + 600],
                            "heading_path": f"Chapter {p}",
                            "token_estimate": 150,
                            "embedding": [v / norm for v in vector],
                            "embedding_model": "perf-random",
                        }
                    )
    await bulk(db, Document, docs)
    await bulk(db, DocumentPage, pages)
    await bulk(db, Chunk, chunks, size=500)
    print(f"  documents: {len(docs)}, pages: {len(pages)}, chunks: {len(chunks)}")

    # The question bank.
    questions: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID]]] = {}
    rows = []
    for module_id in modules:
        questions[module_id] = []
        for _ in range(s.questions_per_module):
            qid, topic_id = uuid.uuid4(), rng.choice(topics[module_id])
            questions[module_id].append((qid, topic_id))
            rows.append(
                {
                    "id": qid,
                    "user_id": uid,
                    "module_id": module_id,
                    "topic_id": topic_id,
                    "type": "multiple_choice",
                    "difficulty": rng.choice(["easy", "medium", "hard"]),
                    "rating": 1500.0,
                    "stem_md": sentence(rng),
                    "solution_md": sentence(rng),
                    "answer_spec": {
                        "type": "multiple_choice",
                        "options": ["a", "b", "c", "d"],
                        "correct": 0,
                    },
                    "origin": "claude",
                }
            )
    await bulk(db, Question, rows)

    # Half a year of quizzes: each answer marked, some with a mistake.
    quizzes, items, attempts, answers = [], [], [], []
    categories = ["sign_error", "wrong_method", "arithmetic_or_algebra_slip", "concept_confusion"]
    skill = {t: rng.uniform(0.3, 0.9) for ts in topics.values() for t in ts}
    for day in range(s.days):
        for _ in range(s.quizzes_per_day):
            module_id = rng.choice(modules)
            at = now - timedelta(days=s.days - day, minutes=rng.randint(0, 600))
            quiz_id, attempt_id = uuid.uuid4(), uuid.uuid4()
            quizzes.append(
                {
                    "id": quiz_id,
                    "user_id": uid,
                    "module_id": module_id,
                    "kind": rng.choice(["daily", "practice"]),
                    "title": "Quiz",
                    "created_at": at,
                }
            )
            chosen = rng.sample(questions[module_id], s.answers_per_quiz)
            scores = []
            for position, (qid, topic_id) in enumerate(chosen):
                items.append(
                    {"quiz_id": quiz_id, "position": position, "user_id": uid, "question_id": qid}
                )
                right = rng.random() < skill[topic_id]
                scores.append(1.0 if right else 0.0)
                answers.append(
                    {
                        "id": uuid.uuid4(),
                        "user_id": uid,
                        "quiz_attempt_id": attempt_id,
                        "question_id": qid,
                        "response": {"choice": 0 if right else 1},
                        "time_ms": rng.randint(20_000, 180_000),
                        "score": scores[-1],
                        "marked_by": "rule",
                        "marked_at": at,
                        "mistake_category": None if right else rng.choice(categories),
                        "created_at": at,
                    }
                )
            attempts.append(
                {
                    "id": attempt_id,
                    "user_id": uid,
                    "quiz_id": quiz_id,
                    "mode": "normal",
                    "status": "marked",
                    "started_at": at,
                    "submitted_at": at,
                    "marked_at": at,
                    "score": sum(scores) / len(scores),
                }
            )
    await bulk(db, Quiz, quizzes)
    await bulk(db, QuizItem, items)
    await bulk(db, QuizAttempt, attempts)
    await bulk(db, QuestionAttempt, answers)
    print(f"  quizzes: {len(attempts)}, answers: {len(answers)}")

    # Flashcards and their review history.
    cards, reviews = [], []
    for module_id in modules:
        for _ in range(s.flashcards_per_module):
            cards.append(
                {
                    "id": uuid.uuid4(),
                    "user_id": uid,
                    "module_id": module_id,
                    "topic_id": rng.choice(topics[module_id]),
                    "front_md": sentence(rng, 8),
                    "back_md": sentence(rng, 10),
                    "origin": "claude",
                    "fsrs_state": 2,
                    "reps": 5,
                    "stability": rng.uniform(1, 60),
                    "fsrs_difficulty": rng.uniform(3, 8),
                    "due": now + timedelta(days=rng.uniform(-3, 40)),
                    "last_review": now - timedelta(days=rng.uniform(1, 20)),
                }
            )
    for day in range(s.days):
        for _ in range(s.reviews_per_day):
            reviews.append(
                {
                    "user_id": uid,
                    "flashcard_id": rng.choice(cards)["id"],
                    "rating": rng.choice([1, 3, 3, 3, 4]),
                    "reviewed_at": now - timedelta(days=s.days - day, minutes=rng.randint(0, 600)),
                    "state_before": 2,
                    "scheduled_days": rng.uniform(1, 30),
                    "duration_ms": rng.randint(3000, 30000),
                }
            )
    await bulk(db, Flashcard, cards)
    await bulk(db, FlashcardReview, reviews)
    print(f"  flashcards: {len(cards)}, reviews: {len(reviews)}")

    materials, versions, exercises = [], [], []
    for module_id in modules:
        for _ in range(s.materials_per_module):
            material_id = uuid.uuid4()
            materials.append(
                {
                    "id": material_id,
                    "user_id": uid,
                    "module_id": module_id,
                    "title": sentence(rng, 4),
                    "kind": "summary",
                    "origin": "claude",
                }
            )
            versions.append(
                {
                    "id": uuid.uuid4(),
                    "material_id": material_id,
                    "user_id": uid,
                    "version_no": 1,
                    "content_md": " ".join(sentence(rng) for _ in range(40)),
                    "created_by": "claude",
                }
            )
        for _ in range(s.exercises_per_module):
            exercises.append(
                {
                    "id": uuid.uuid4(),
                    "user_id": uid,
                    "module_id": module_id,
                    "language": "python",
                    "title": sentence(rng, 4),
                    "prompt_md": sentence(rng),
                    "starter_code": "def f(x):\n    pass\n",
                    "solution_code": "def f(x):\n    return x\n",
                    "difficulty": "medium",
                    "origin": "claude",
                    "tests": [{"name": "t", "code": "assert f(1) == 1", "hidden": False}],
                }
            )
    await bulk(db, Material, materials)
    await bulk(db, MaterialVersion, versions)
    for row, version in zip(materials, versions, strict=True):
        await db.execute(
            update(Material)
            .where(Material.id == row["id"])
            .values(current_version_id=version["id"])
        )
    await bulk(db, CodingExercise, exercises)
    await db.commit()

    for module_id in modules:
        await recompute(db, uid, module_id, config, now)
    await db.commit()
    print(f"seeded in {time.perf_counter() - started:.0f} s")


# --- measuring -------------------------------------------------------------------------------


class NoJobs:
    async def enqueue(self, function: str, *args: object, job_id: str | None = None) -> None:
        return None


async def app_client(config: AppConfig) -> tuple[httpx.AsyncClient, Any, list[Any]]:
    settings = get_settings()
    app = create_app()
    engine = create_engine(perf_url())
    embedder = create_provider(config.retrieval.embeddings, settings.model_cache_dir)
    await embedder.warm_up()
    redis = Redis.from_url(settings.redis_url)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.redis = redis
    app.state.jobs = NoJobs()
    app.state.storage = create_storage(settings)
    app.state.claude = create_client(None, config.ai)
    app.state.embedder = embedder
    app.state.push = None
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 50000)), base_url="https://perf"
    )
    login = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    login.raise_for_status()
    client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]
    return client, app, [engine, redis]


def p(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]


async def time_one(client: httpx.AsyncClient, url: str) -> float:
    started = time.perf_counter()
    response = await client.get(url)
    elapsed = (time.perf_counter() - started) * 1000
    if response.status_code != 200:
        raise RuntimeError(f"{url} -> {response.status_code}: {response.text[:200]}")
    return elapsed


async def measure(config: AppConfig) -> int:
    perf = config.platform.performance
    # Measure the server, not this terminal: request logs at INFO go to a
    # slow pipe here, but to a log driver when deployed.
    client, _, closers = await app_client(config)
    configure_logging("WARNING")  # after create_app, which sets its own level
    freeze_heap()  # as the app's start-up does, once the model is loaded
    try:
        modules = (await client.get("/api/v1/modules")).json()
        m = modules[0]["id"]
        today = date.today()
        start = today - timedelta(days=today.weekday())
        groups: dict[str, list[str]] = {
            "page": [
                "/api/v1/analytics/overview",
                "/api/v1/analytics/dashboard",
                "/api/v1/plan",
                "/api/v1/daily-quiz/plan",
                "/api/v1/flashcards/due",
                "/api/v1/progress/weakest",
                "/api/v1/recommendations",
                "/api/v1/notifications",
                "/api/v1/mistakes",
                "/api/v1/exams",
                "/api/v1/modules",
                f"/api/v1/analytics/modules/{m}",
                f"/api/v1/progress?module_id={m}",
                f"/api/v1/questions?module_id={m}",
                f"/api/v1/coding/exercises?module_id={m}",
                f"/api/v1/documents?module_id={m}",
                f"/api/v1/materials?module_id={m}",
                "/api/v1/session-builder?minutes=45",
                "/api/v1/planner/preferences",
            ],
            "history": [
                "/api/v1/analytics/trends",
                "/api/v1/analytics/readiness",
                "/api/v1/profile",
                f"/api/v1/calendar?start={start}&end={start + timedelta(days=41)}",
            ],
            "search": [
                f"/api/v1/search?q={q}"
                for q in ("ratio test", "eigenvalue matrix", "variance estimator")
            ],
        }
        # The first read of the day replans; time it separately, then warm up.
        cold = await time_one(client, "/api/v1/plan")
        print(f"first plan of the day (replans): {cold:.0f} ms")
        failures = 0
        print(f"\n{'endpoint':62} {'p50':>7} {'p95':>7} {'target':>7}")
        for group, urls in groups.items():
            target = getattr(perf.targets_ms, group)
            for url in urls:
                for _ in range(3):
                    await time_one(client, url)
                times = [await time_one(client, url) for _ in range(perf.samples)]
                p95 = p(times, 0.95)
                ok = p95 <= target
                failures += not ok
                mark = "" if ok else "  MISSED"
                median = statistics.median(times)
                print(f"{url[:62]:62} {median:7.0f} {p95:7.0f} {target:7d}{mark}")

        # A burst of concurrent clients over the page endpoints.
        deadline = time.perf_counter() + perf.burst_seconds
        latencies: list[float] = []
        errors: list[str] = []

        async def worker(seed: int) -> None:
            rng = random.Random(seed)  # noqa: S311 - load pattern only
            while time.perf_counter() < deadline:
                try:
                    latencies.append(await time_one(client, rng.choice(groups["page"])))
                except RuntimeError as exc:
                    errors.append(str(exc))

        await asyncio.gather(*(worker(i) for i in range(perf.concurrency)))
        limit = perf.targets_ms.page * perf.burst_slowdown
        burst_p95 = p(latencies, 0.95)
        ok = not errors and burst_p95 <= limit
        failures += not ok
        mark = "" if ok else "  MISSED"
        print(
            f"\nburst: {perf.concurrency} clients, {len(latencies)} requests "
            f"in {perf.burst_seconds} s, p95 {burst_p95:.0f} ms (limit {limit:.0f}), "
            f"errors {len(errors)}{mark}"
        )
        for error in errors[:3]:
            print("  ", error)
        print("\nall targets met" if not failures else f"\n{failures} target(s) missed")
        return 1 if failures else 0
    finally:
        await client.aclose()
        for closer in closers:
            await (closer.dispose() if hasattr(closer, "dispose") else closer.aclose())


async def main(reseed: bool) -> int:
    config = get_config()
    await ensure_database()
    engine = create_engine(perf_url())
    try:
        async with create_session_factory(engine)() as db:
            if reseed and await db.scalar(select(User.id).where(User.email == EMAIL)):
                print("--reseed: drop the perf database first (DROP DATABASE revision_os_perf).")
                return 2
            await seed(db, config)
    finally:
        await engine.dispose()
    return await measure(config)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reseed", action="store_true", help="refuse to reuse an existing seed")
    raise SystemExit(asyncio.run(main(parser.parse_args().reseed)))
