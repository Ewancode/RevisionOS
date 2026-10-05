"""The scheduler process (ARCHITECTURE.md section 4):
``arq app.workers.scheduler.SchedulerSettings``.

- Every few minutes it pushes reminders to your devices (planner.yaml
  notifications.push_every_minutes), when push is set up (VAPID keys in .env).
- Daily it empties the trash of items deleted over 30 days ago (app/trash.py).
"""

import logging
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.core.clock import utcnow
from app.core.config import get_config
from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.db.session import create_engine, create_session_factory
from app.planner.push import create_sender, dispatch
from app.storage import create_storage
from app.trash import purge

logger = logging.getLogger(__name__)
_every = get_config().planner.notifications.push_every_minutes


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings.database_url.get_secret_value())
    ctx["engine"] = engine
    ctx["sessions"] = create_session_factory(engine)
    ctx["storage"] = create_storage(settings)
    ctx["sender"] = create_sender(
        settings.vapid_public_key,
        settings.vapid_private_key.get_secret_value() if settings.vapid_private_key else None,
        settings.vapid_subject,
        get_config().planner.notifications.push_hosts,
    )
    if ctx["sender"] is None:
        logger.info("push is off: no VAPID keys")


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()


async def push_reminders(ctx: dict[str, Any]) -> int:
    if ctx["sender"] is None:
        return 0
    async with ctx["sessions"]() as db:
        sent = await dispatch(db, ctx["sender"], get_config(), utcnow())
    if sent:
        logger.info("pushed reminders", extra={"delivered": sent})
    return sent


async def empty_trash(ctx: dict[str, Any]) -> dict[str, int]:
    config = get_config()
    async with ctx["sessions"]() as db:
        return await purge(db, ctx["storage"], config.platform.trash.retention_days, utcnow())


class SchedulerSettings:
    cron_jobs: ClassVar[list[Any]] = [
        cron(push_reminders, minute=set(range(0, 60, _every)), unique=True, timeout=240),
        cron(
            empty_trash,
            hour=get_config().platform.trash.purge_hour,
            minute=17,
            unique=True,
            timeout=600,
        ),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # Its own queue, so the worker never picks up scheduler jobs or the reverse.
    queue_name = "arq:scheduler"
