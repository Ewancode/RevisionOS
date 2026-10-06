"""Local-disk storage for development and single-machine use."""

import asyncio
import os
import re
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from app.storage.base import StorageKeyError, validate_key

_USER_PREFIX = re.compile(r"users/[0-9a-f-]{36}/")


def _is_key(key: str) -> bool:
    try:
        validate_key(key)
    except StorageKeyError:
        return False
    return True


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / validate_key(key)).resolve()
        # Belt and braces: the resolved path must stay inside the root.
        if not path.is_relative_to(self.root):
            raise StorageKeyError(f"key escapes storage root: {key!r}")
        return path

    def _prefix_path(self, prefix: str) -> Path:
        path = (self.root / prefix).resolve()
        if not prefix.endswith("/") or not path.is_relative_to(self.root) or path == self.root:
            raise StorageKeyError(f"invalid prefix: {prefix!r}")
        validate_key(prefix + "original")
        return path

    async def put_file(self, key: str, source: Path) -> None:
        target = self._path(key)

        def copy() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".tmp")
            shutil.copyfile(source, tmp)
            os.replace(tmp, target)  # atomic: readers never see a partial file

        await asyncio.to_thread(copy)

    async def put_bytes(self, key: str, data: bytes) -> None:
        target = self._path(key)

        def write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, target)

        await asyncio.to_thread(write)

    async def read_bytes(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def stream(self, key: str, chunk_size: int = 64 * 1024) -> AsyncIterator[bytes]:
        path = self._path(key)
        handle = await asyncio.to_thread(path.open, "rb")
        try:
            while chunk := await asyncio.to_thread(handle.read, chunk_size):
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, True)

    async def list_keys(self, prefix: str) -> list[str]:
        base = self._user_prefix_path(prefix)

        def walk() -> list[str]:
            if not base.is_dir():
                return []
            keys = (
                f"{prefix}{p.relative_to(base).as_posix()}"
                for p in base.rglob("*")
                if p.is_file() and not p.name.endswith(".tmp")
            )
            return sorted(k for k in keys if _is_key(k))

        return await asyncio.to_thread(walk)

    def _user_prefix_path(self, prefix: str) -> Path:
        if not _USER_PREFIX.fullmatch(prefix):
            raise StorageKeyError(f"invalid prefix: {prefix!r}")
        return self.root / prefix

    async def delete_prefix(self, prefix: str) -> None:
        path = self._prefix_path(prefix)
        await asyncio.to_thread(shutil.rmtree, path, True)

    @asynccontextmanager
    async def local_copy(self, key: str) -> AsyncIterator[Path]:
        yield self._path(key)
