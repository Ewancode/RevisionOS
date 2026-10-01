"""Enqueueing background jobs, behind a small interface tests can replace."""

from typing import Any, Protocol

from arq.connections import ArqRedis


class JobQueue(Protocol):
    async def enqueue(self, function: str, *args: Any, job_id: str | None = None) -> None: ...


class ArqQueue:
    def __init__(self, redis: ArqRedis) -> None:
        self.redis = redis

    async def enqueue(self, function: str, *args: Any, job_id: str | None = None) -> None:
        # A job id makes enqueueing idempotent: a second request for the same
        # work while the first is pending is dropped by arq.
        await self.redis.enqueue_job(function, *args, _job_id=job_id)
