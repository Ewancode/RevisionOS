"""Structured JSON logging with a per-request ID carried through contextvars."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else was passed via `extra=`.
_STANDARD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id is not None:
            payload["request_id"] = request_id
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _AppHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Marks the handler this module installs, so reconfiguring replaces only it."""


def configure_logging(level: str) -> None:
    handler = _AppHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for existing in [h for h in root.handlers if isinstance(h, _AppHandler)]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)
    # Our middleware writes one structured access line per request.
    logging.getLogger("uvicorn.access").disabled = True
