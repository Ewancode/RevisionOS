"""Password hashing and opaque session/CSRF tokens (ARCHITECTURE.md section 12)."""

import hashlib
import hmac
import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# `__Host-` cookies must be Secure, have Path=/ and no Domain, so they cannot
# be set or overwritten by another (sub)domain.
SESSION_COOKIE = "__Host-rev_session"
CSRF_COOKIE = "__Host-rev_csrf"
CSRF_HEADER = "X-CSRF-Token"

TOKEN_BYTES = 32  # 256 bits

# Argon2id with the library's RFC 9106 defaults.
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@lru_cache
def _dummy_hash() -> str:
    return _hasher.hash(secrets.token_urlsafe(16))


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check when the email is unknown, so
    response timing does not reveal which accounts exist."""
    verify_password(_dummy_hash(), password)


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def token_matches(token: str, expected_hash: bytes) -> bool:
    return hmac.compare_digest(hash_token(token), expected_hash)
