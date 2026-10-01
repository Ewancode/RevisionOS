"""The error envelope and request-ID contract from ARCHITECTURE.md section 4."""

import logging

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from app.core.errors import AppError
from app.core.middleware import REQUEST_ID_HEADER


class Payload(BaseModel):
    count: int


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail at /srv/app/db.py line 42")

    @app.get("/app-error")
    async def app_error() -> None:
        raise AppError("module_archived", "This module is archived.", status_code=409)

    @app.post("/validate")
    async def validate(body: Payload) -> Payload:
        return body

    return app


def _assert_envelope(response: httpx.Response, code: str) -> dict[str, object]:
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert error["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert isinstance(error, dict)
    return error


async def test_unexpected_exception_is_hidden_and_logged(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        response = await client.get("/boom")

    assert response.status_code == 500
    _assert_envelope(response, "internal_error")
    assert "secret internal detail" not in response.text
    assert "Traceback" not in response.text
    logged = [r for r in caplog.records if r.exc_info]
    assert logged and "secret internal detail" in str(logged[0].exc_info[1])  # type: ignore[index]


async def test_app_error_uses_its_code_and_status(client: httpx.AsyncClient) -> None:
    response = await client.get("/app-error")
    assert response.status_code == 409
    error = _assert_envelope(response, "module_archived")
    assert error["message"] == "This module is archived."


async def test_unknown_route_returns_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    _assert_envelope(response, "not_found")


async def test_wrong_method_returns_envelope(client: httpx.AsyncClient) -> None:
    response = await client.delete("/api/v1/health")
    assert response.status_code == 405
    _assert_envelope(response, "method_not_allowed")


async def test_validation_error_lists_fields_without_echoing_input(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/validate", json={"count": "not-a-number-SENSITIVE"})
    assert response.status_code == 422
    error = _assert_envelope(response, "validation_error")
    details = error["details"]
    assert isinstance(details, list) and len(details) == 1
    assert details[0]["loc"] == ["body", "count"]
    assert set(details[0]) == {"loc", "msg"}
    assert "SENSITIVE" not in response.text


async def test_valid_caller_request_id_is_kept(client: httpx.AsyncClient) -> None:
    response = await client.get("/app-error", headers={REQUEST_ID_HEADER: "trace-123"})
    assert response.headers[REQUEST_ID_HEADER] == "trace-123"
    assert response.json()["error"]["request_id"] == "trace-123"


@pytest.mark.parametrize("bad", [b"x" * 65, b"has space", b"inject\xe2\x80\xa8line", b""])
async def test_unsafe_caller_request_id_is_replaced(client: httpx.AsyncClient, bad: bytes) -> None:
    response = await client.get("/api/v1/health", headers={REQUEST_ID_HEADER.encode(): bad})
    assert response.headers[REQUEST_ID_HEADER].encode() != bad
    assert len(response.headers[REQUEST_ID_HEADER]) == 32
