import pytest
from fakeredis import FakeAsyncRedis

from app.core.config import RateLimit
from app.core.rate_limit import RateLimiter
from app.core.security import (
    hash_password,
    hash_token,
    new_token,
    token_matches,
    verify_password,
)


def test_password_hashing_uses_argon2id_and_verifies() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse battery staple")
    assert not verify_password(hashed, "Correct horse battery staple")
    assert not verify_password("not-a-hash", "anything")


def test_tokens_are_random_and_compared_by_hash() -> None:
    a, b = new_token(), new_token()
    assert a != b
    assert len(a) >= 43  # 32 random bytes, base64url
    assert token_matches(a, hash_token(a))
    assert not token_matches(b, hash_token(a))


async def test_rate_limiter_blocks_after_the_limit_and_resets() -> None:
    limiter = RateLimiter(FakeAsyncRedis())
    limit = RateLimit(max_attempts=2, window_seconds=60)
    key = limiter.key("login:ip", "203.0.113.1")

    assert (await limiter.hit(key, limit)).allowed
    assert (await limiter.hit(key, limit)).allowed
    blocked = await limiter.hit(key, limit)
    assert not blocked.allowed
    assert 0 < blocked.retry_after_seconds <= 60

    await limiter.reset(key)
    assert (await limiter.hit(key, limit)).allowed


def test_rate_limit_keys_do_not_contain_the_subject() -> None:
    key = RateLimiter.key("login:email", "ewan@example.com")
    assert "ewan" not in key


@pytest.mark.parametrize("subject", ["a", "b"])
def test_rate_limit_keys_are_stable(subject: str) -> None:
    assert RateLimiter.key("s", subject) == RateLimiter.key("s", subject)
