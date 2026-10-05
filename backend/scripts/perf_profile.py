"""Where the time goes: the shared building blocks of the slow endpoints,
timed on the perf database, with the top functions by cumulative time.
Usage (inside the api container): python -m scripts.perf_profile [name]"""

import asyncio
import cProfile
import io
import pstats
import sys
import time

from sqlalchemy import select

from app.core.clock import utcnow
from app.core.config import get_config
from app.db.session import create_engine, create_session_factory
from app.learning import daily
from app.learning.mistakes import mistake_bank
from app.learning.profile import metrics
from app.models import User
from app.planner.context import load
from app.services.analytics import AnalyticsService
from app.services.common import ClientInfo
from app.services.learning import LearningService
from scripts.perf import EMAIL, perf_url


async def main(only: str | None) -> None:
    config = get_config()
    engine = create_engine(perf_url())
    factory = create_session_factory(engine)
    async with factory() as db:
        user_id = await db.scalar(select(User.id).where(User.email == EMAIL))
        if user_id is None:
            raise SystemExit("Seed the perf database first: make perf")
        now = utcnow()
        analytics = AnalyticsService(db, user_id, ClientInfo(None, None), config=config)
        learning = LearningService(db, user_id, ClientInfo(None, None), config=config, jobs=None)  # type: ignore[arg-type]

        async def due_route() -> None:
            cards, _ = await learning.due(None)
            for card in cards:
                learning.intervals(card)

        blocks = {
            "planner.load": lambda: load(db, user_id, config, now),
            "mistake_bank": lambda: mistake_bank(db, user_id, config, now),
            "daily.plan": lambda: daily.plan(db, user_id, config, now),
            "profile.metrics": lambda: metrics(db, user_id, config, now),
            "analytics.overview": analytics.overview,
            "learning.due": lambda: learning.due(None),
            "due.route": due_route,
        }
        for name, block in blocks.items():
            if only and name != only:
                continue
            await block()  # warm
            times = []
            for _ in range(5):
                started = time.perf_counter()
                await block()
                times.append((time.perf_counter() - started) * 1000)
            print(f"{name:22} median {sorted(times)[2]:7.0f} ms")
            if only:
                profiler = cProfile.Profile()
                profiler.enable()
                await block()
                profiler.disable()
                out = io.StringIO()
                pstats.Stats(profiler, stream=out).sort_stats("cumulative").print_stats(25)
                print(out.getvalue()[:6000])
    await engine.dispose()


asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
