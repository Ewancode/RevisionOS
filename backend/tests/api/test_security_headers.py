import httpx
import pytest

from app.core.settings import Settings
from app.main import create_app


async def test_security_headers_on_every_response(client: httpx.AsyncClient) -> None:
    for path in ("/api/v1/health", "/api/v1/does-not-exist"):
        headers = (await client.get(path)).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
        assert "default-src 'none'" in headers["content-security-policy"]
        assert headers["cache-control"] == "no-store"
        assert "strict-transport-security" not in headers  # HTTPS-only header: production


async def test_hsts_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    prod = create_app(Settings(_env_file=None))
    transport = httpx.ASGITransport(app=prod)
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as c:
        response = await c.get("/api/v1/health")
    assert response.headers["strict-transport-security"].startswith("max-age=")
