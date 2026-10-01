import json
import logging

from app.core.logging import JsonFormatter, request_id_var


def _record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.makeLogRecord({"name": "t", "levelname": "INFO", "msg": msg})
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formats_as_json_with_request_id_and_extras() -> None:
    token = request_id_var.set("abc123")
    try:
        line = JsonFormatter().format(_record("hello", status=200))
    finally:
        request_id_var.reset(token)

    payload = json.loads(line)
    assert payload["message"] == "hello"
    assert payload["request_id"] == "abc123"
    assert payload["status"] == 200
    assert payload["level"] == "INFO"


def test_omits_request_id_outside_a_request() -> None:
    payload = json.loads(JsonFormatter().format(_record("idle")))
    assert "request_id" not in payload
