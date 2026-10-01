from arq.connections import RedisSettings

from app.core.settings import get_settings
from app.workers.settings import WorkerSettings
from app.workers.tasks import ping


async def test_ping_task() -> None:
    assert await ping({}) == "pong"


def test_worker_registers_tasks_and_reads_redis_url() -> None:
    assert ping in WorkerSettings.functions
    expected = RedisSettings.from_dsn(get_settings().redis_url)
    assert (WorkerSettings.redis_settings.host, WorkerSettings.redis_settings.port) == (
        expected.host,
        expected.port,
    )
