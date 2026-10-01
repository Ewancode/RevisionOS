"""Arq worker entry point: ``arq app.workers.settings.WorkerSettings``.

The separate cron ``scheduler`` process from ARCHITECTURE.md section 4 is
added in the first phase that has a scheduled job.
"""

from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.core.config import get_config
from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.workers.tasks import ping


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(get_settings().log_level)
    get_config()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
