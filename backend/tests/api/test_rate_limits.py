"""Per-account rate limits on routes that call Claude, uploads and test
pushes (security audit, Phase 12)."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.main import create_app
from tests.support import make_user, signed_in

# Every route that can call Claude (or is otherwise costly), and its limit.
LIMITED = {
    ("POST", "/api/v1/conversations/{conversation_id}/messages"): "ai",
    ("POST", "/api/v1/drafts"): "ai",
    ("POST", "/api/v1/drafts/{draft_id}/regenerate"): "ai",
    ("POST", "/api/v1/documents/{document_id}/reprocess"): "ai",
    ("POST", "/api/v1/documents/{document_id}/pages/{page_no}/retranscribe"): "ai",
    ("POST", "/api/v1/attempts/{attempt_id}/submit"): "ai",
    ("POST", "/api/v1/answers/{answer_id}/dispute"): "ai",
    ("POST", "/api/v1/attempts/{attempt_id}/responses/{question_id}/photo"): "ai",
    ("POST", "/api/v1/daily-quiz"): "ai",
    ("POST", "/api/v1/availability/parse"): "ai",
    ("POST", "/api/v1/coding/exercises/{exercise_id}/hints"): "ai",
    ("POST", "/api/v1/attempts/{attempt_id}/responses/{question_id}/hints"): "ai",
    ("POST", "/api/v1/documents"): "uploads",
    ("POST", "/api/v1/push/test"): "push_test",
}


def scopes(route: APIRoute) -> set[str]:
    found: set[str] = set()
    for dep in route.dependant.dependencies:
        scope = getattr(dep.call, "rate_limit_scope", None)
        if isinstance(scope, str):
            found.add(scope)
    return found


def api_routes(router: Any, inherited: str = "") -> Iterator[tuple[tuple[str, str], APIRoute]]:
    """Every route object with its full path (FastAPI nests included
    routers; this matches the OpenAPI paths exactly)."""
    for route in router.routes:
        if isinstance(route, APIRoute):
            for method in route.methods or ():
                yield (method, inherited + route.path), route
        elif hasattr(route, "original_router"):
            yield from api_routes(route.original_router, inherited + getattr(router, "prefix", ""))


def test_every_costly_route_is_rate_limited() -> None:
    app = create_app()
    found = {key: scopes(route) for key, route in api_routes(app.router)}
    assert len(found) == sum(len(ops) for ops in app.openapi()["paths"].values())
    for key, scope in LIMITED.items():
        assert key in found, key
        assert found[key] == {scope}, key


@pytest.fixture
def strict_app(db_app: FastAPI) -> FastAPI:
    """Test pushes limited to 2 per window."""
    config = get_config()
    limits = config.platform.rate_limits.model_copy(
        update={
            "push_test": config.platform.rate_limits.push_test.model_copy(
                update={"max_attempts": 2}
            )
        }
    )
    patched = config.model_copy(
        update={"platform": config.platform.model_copy(update={"rate_limits": limits})}
    )
    db_app.dependency_overrides[get_config] = lambda: patched
    return db_app


@pytest.mark.db
async def test_limits_are_per_account(strict_app: FastAPI, db: AsyncSession) -> None:
    alice = await make_user(db, "alice@example.com", "Alice")
    bob = await make_user(db, "bob@example.com", "Bob")
    async with signed_in(strict_app, alice) as a:
        codes = [(await a.post("/api/v1/push/test")).status_code for _ in range(3)]
        assert codes[:2] == [409, 409]  # push is off in tests, but the request counts
        assert codes[2] == 429
        blocked = await a.post("/api/v1/push/test")
        assert blocked.json()["error"]["code"] == "rate_limited"
        assert "Try again in" in blocked.json()["error"]["message"]
    async with signed_in(strict_app, bob) as b:
        assert (await b.post("/api/v1/push/test")).status_code == 409
