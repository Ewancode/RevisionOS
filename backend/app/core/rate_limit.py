"""Fixed-window rate limiting in Redis."""

import hashlib
from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.config import RateLimit


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def key(scope: str, subject: str) -> str:
        # Subjects (IPs, emails) are hashed so Redis never holds them in clear.
        digest = hashlib.sha256(subject.encode()).hexdigest()[:32]
        return f"rl:{scope}:{digest}"

    async def hit(self, key: str, limit: RateLimit) -> RateLimitResult:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, limit.window_seconds, nx=True)
            pipe.ttl(key)
            count, _, ttl = await pipe.execute()
        if int(count) > limit.max_attempts:
            return RateLimitResult(False, max(int(ttl), 1))
        return RateLimitResult(True, 0)

    async def reset(self, *keys: str) -> None:
        if keys:
            await self._redis.delete(*keys)
