import asyncio

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1 import health
from app.api.v1.health import Check, get_readiness_checks
from app.core.settings import Settings
from app.main import create_app


async def _ok() -> None:
    return None


async def _fail() -> None:
    raise ConnectionError("refused")


async def _hang() -> None:
    await asyncio.sleep(10)


def _use_checks(app: FastAPI, checks: dict[str, Check]) -> None:
    app.dependency_overrides[get_readiness_checks] = lambda: checks


async def test_liveness(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_when_all_dependencies_answer(app: FastAPI, client: httpx.AsyncClient) -> None:
    _use_checks(app, {"database": _ok, "redis": _ok})
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok", "redis": "ok"}}


async def test_not_ready_when_a_dependency_fails(app: FastAPI, client: httpx.AsyncClient) -> None:
    _use_checks(app, {"database": _ok, "redis": _fail})
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "ok", "redis": "unavailable"},
    }
    assert "refused" not in response.text


async def test_hung_dependency_times_out(
    app: FastAPI, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "CHECK_TIMEOUT_SECONDS", 0.05)
    _use_checks(app, {"database": _hang})
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "unavailable"}


async def test_api_docs_disabled_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    prod = create_app(Settings(_env_file=None))
    transport = httpx.ASGITransport(app=prod)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        assert (await c.get("/api/docs")).status_code == 404
        assert (await c.get("/api/openapi.json")).status_code == 404
