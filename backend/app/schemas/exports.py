import uuid
from datetime import datetime
from typing import Literal

from app.schemas.common import Output


class DataJobOut(Output):
    id: uuid.UUID
    kind: Literal["export", "restore"]
    status: Literal["queued", "running", "done", "failed"]
    size_bytes: int | None
    # Rows per table (and "files") written or restored.
    counts: dict[str, int] | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None
    # Exports: when the download is deleted (None once it has been, or for restores).
    expires_at: datetime | None = None
