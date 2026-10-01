"""Raw file storage behind one interface (ARCHITECTURE.md section 6)."""

from app.core.settings import Settings
from app.storage.base import StorageBackend, StorageKeyError, document_key, page_image_key
from app.storage.local import LocalStorage


def create_storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "local":
        return LocalStorage(settings.storage_local_root)
    raise ValueError(f"unknown storage backend: {settings.storage_backend}")


__all__ = [
    "LocalStorage",
    "StorageBackend",
    "StorageKeyError",
    "create_storage",
    "document_key",
    "page_image_key",
]
