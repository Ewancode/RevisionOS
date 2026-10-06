"""Raw file storage behind one interface (ARCHITECTURE.md section 6)."""

from app.core.settings import Settings
from app.storage.base import StorageBackend, StorageKeyError, document_key, page_image_key
from app.storage.local import LocalStorage
from app.storage.s3 import S3Storage


def create_storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "local":
        return LocalStorage(settings.storage_local_root)
    if settings.storage_backend == "s3":
        if not settings.s3_bucket:
            raise ValueError("STORAGE_BACKEND=s3 needs S3_BUCKET (and its keys) in .env")
        secret = settings.s3_secret_access_key
        return S3Storage(
            settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url or None,
            region=settings.s3_region or None,
            access_key_id=settings.s3_access_key_id or None,
            secret_access_key=secret.get_secret_value() if secret else None,
        )
    raise ValueError(f"unknown storage backend: {settings.storage_backend}")


__all__ = [
    "LocalStorage",
    "S3Storage",
    "StorageBackend",
    "StorageKeyError",
    "create_storage",
    "document_key",
    "page_image_key",
]
