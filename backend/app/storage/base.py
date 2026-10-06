"""The storage interface and the only functions that build storage keys.

Keys are built from server-generated UUIDs and fixed words, never from
anything a user typed, so a hostile filename cannot reach a path. Backends
still validate every key they are given, as a second line of defence.
"""

import re
import uuid
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Protocol

# users/<uuid>/documents/<uuid>/(original | pages/<n>.png)
_KEY = re.compile(
    r"^users/[0-9a-f-]{36}/("
    r"documents/[0-9a-f-]{36}/(original|pages/[1-9][0-9]{0,4}\.png)"
    # Photos of handwritten working (re-encoded to PNG or JPEG on upload).
    r"|answers/[0-9a-f-]{36}/[0-9a-f-]{36}\.(png|jpeg)"
    # Your data exports, and archives uploaded to restore (Phase 13).
    r"|(exports|imports)/[0-9a-f-]{36}\.zip"
    r")$"
)
# What an export carries: your files, not other exports.
DATA_FOLDERS = ("documents/", "answers/")


class StorageKeyError(ValueError):
    pass


def validate_key(key: str) -> str:
    if not _KEY.fullmatch(key):
        raise StorageKeyError(f"invalid storage key: {key!r}")
    return key


def document_key(user_id: uuid.UUID, document_id: uuid.UUID) -> str:
    return validate_key(f"users/{user_id}/documents/{document_id}/original")


def page_image_key(user_id: uuid.UUID, document_id: uuid.UUID, page_no: int) -> str:
    return validate_key(f"users/{user_id}/documents/{document_id}/pages/{page_no}.png")


def answer_image_key(
    user_id: uuid.UUID, attempt_id: uuid.UUID, question_id: uuid.UUID, ext: str
) -> str:
    """A photo of handwritten working for one answer."""
    return validate_key(f"users/{user_id}/answers/{attempt_id}/{question_id}.{ext}")


def archive_key(user_id: uuid.UUID, job_id: uuid.UUID, kind: str) -> str:
    """An export's ZIP, or an uploaded one waiting to be restored."""
    folder = {"export": "exports", "restore": "imports"}[kind]
    return validate_key(f"users/{user_id}/{folder}/{job_id}.zip")


def document_prefix(user_id: uuid.UUID, document_id: uuid.UUID) -> str:
    return f"users/{user_id}/documents/{document_id}/"


def user_prefix(user_id: uuid.UUID) -> str:
    return f"users/{user_id}/"


class StorageBackend(Protocol):
    async def put_file(self, key: str, source: Path) -> None:
        """Store a local file under `key`, replacing any existing object."""

    async def put_bytes(self, key: str, data: bytes) -> None: ...

    async def read_bytes(self, key: str) -> bytes: ...

    def stream(self, key: str, chunk_size: int = 64 * 1024) -> AsyncIterator[bytes]: ...

    async def exists(self, key: str) -> bool: ...

    async def delete(self, key: str) -> None:
        """Delete one object; a missing one is not an error."""

    async def delete_prefix(self, prefix: str) -> None:
        """Delete every object under a document's prefix."""

    async def list_keys(self, prefix: str) -> list[str]:
        """Every key under a user's prefix (``users/<uuid>/``), sorted."""

    def local_copy(self, key: str) -> AbstractAsyncContextManager[Path]:
        """The object as a local file, for parsers that need a path: the file
        itself for local storage; a temporary download, removed on exit, for
        a remote backend."""
