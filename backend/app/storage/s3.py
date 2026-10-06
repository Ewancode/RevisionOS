"""A private S3-compatible bucket for deployment (ARCHITECTURE.md section 6):
Cloudflare R2 or Backblaze B2, or AWS S3 itself.

boto3 is synchronous, so every call runs in a worker thread. The bucket
must not be public: files leave only through the API's ownership checks.
"""

import asyncio
import re
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.storage.base import StorageKeyError, validate_key

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_s3.type_defs import ObjectIdentifierTypeDef

_USER_PREFIX = re.compile(r"users/[0-9a-f-]{36}/")
_DOCUMENT_PREFIX = re.compile(r"users/[0-9a-f-]{36}/documents/[0-9a-f-]{36}/")


class S3Storage:
    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        client: "S3Client | None" = None,
    ) -> None:
        self.bucket = bucket
        self.client: S3Client = client or boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(retries={"max_attempts": 5, "mode": "standard"}),
        )

    async def put_file(self, key: str, source: Path) -> None:
        # upload_file switches to multipart for large files by itself.
        key = validate_key(key)
        await asyncio.to_thread(self.client.upload_file, str(source), self.bucket, key)

    async def put_bytes(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(
            self.client.put_object, Bucket=self.bucket, Key=validate_key(key), Body=data
        )

    async def read_bytes(self, key: str) -> bytes:
        response = await asyncio.to_thread(
            self.client.get_object, Bucket=self.bucket, Key=validate_key(key)
        )
        body: Any = response["Body"]
        try:
            return bytes(await asyncio.to_thread(body.read))
        finally:
            body.close()

    async def stream(self, key: str, chunk_size: int = 64 * 1024) -> AsyncIterator[bytes]:
        response = await asyncio.to_thread(
            self.client.get_object, Bucket=self.bucket, Key=validate_key(key)
        )
        body: Any = response["Body"]
        try:
            while chunk := await asyncio.to_thread(body.read, chunk_size):
                yield chunk
        finally:
            body.close()

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(
                self.client.head_object, Bucket=self.bucket, Key=validate_key(key)
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
        return True

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(
            self.client.delete_object, Bucket=self.bucket, Key=validate_key(key)
        )

    async def _keys(self, prefix: str) -> list[str]:
        def collect() -> list[str]:
            keys: list[str] = []
            pages = self.client.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket, Prefix=prefix
            )
            for page in pages:
                keys.extend(obj["Key"] for obj in page.get("Contents", []) if "Key" in obj)
            return keys

        return await asyncio.to_thread(collect)

    async def delete_prefix(self, prefix: str) -> None:
        if not _DOCUMENT_PREFIX.fullmatch(prefix):
            raise StorageKeyError(f"invalid prefix: {prefix!r}")
        keys = await self._keys(prefix)
        for start in range(0, len(keys), 1000):  # the API's limit per request
            batch: list[ObjectIdentifierTypeDef] = [{"Key": k} for k in keys[start : start + 1000]]
            await asyncio.to_thread(
                self.client.delete_objects, Bucket=self.bucket, Delete={"Objects": batch}
            )

    async def list_keys(self, prefix: str) -> list[str]:
        if not _USER_PREFIX.fullmatch(prefix):
            raise StorageKeyError(f"invalid prefix: {prefix!r}")
        return sorted(k for k in await self._keys(prefix) if _is_key(k))

    @asynccontextmanager
    async def local_copy(self, key: str) -> AsyncIterator[Path]:
        validate_key(key)
        with tempfile.TemporaryDirectory(prefix="revision-os-s3-") as tmp:
            path = Path(tmp) / "object"
            await asyncio.to_thread(self.client.download_file, self.bucket, key, str(path))
            yield path


def _is_key(key: str) -> bool:
    try:
        validate_key(key)
    except StorageKeyError:
        return False
    return True
