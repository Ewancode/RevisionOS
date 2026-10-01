"""Access control across every route (ARCHITECTURE.md sections 12 and 13).

1. Every route outside an explicit public allow-list rejects anonymous calls.
   The route list is read from the app, so a new endpoint is covered
   automatically.
2. IDOR: a second user gets 404 — not 403, which would confirm the id
   exists — for every route that takes another user's resource id, and
   the owner's data is unchanged afterwards.
"""

import re
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from tests import factories
from tests.support import make_user, signed_in

pytestmark = pytest.mark.db

PUBLIC = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/health/ready"),
    ("POST", "/api/v1/auth/login"),
}


def _routes(app: FastAPI) -> list[tuple[str, str]]:
    """Every API operation, from the OpenAPI schema (the stable public view
    of the app's routes; FastAPI nests included routers internally)."""
    return sorted(
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    )


def test_public_allow_list_is_current(app: FastAPI) -> None:
    assert set(_routes(app)) >= PUBLIC


async def test_every_other_route_rejects_anonymous_requests(
    db_app: FastAPI, anon: httpx.AsyncClient
) -> None:
    checked = 0
    for method, path in _routes(db_app):
        if (method, path) in PUBLIC:
            continue
        url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
        response = await anon.request(method, url, json={})
        assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
        assert response.json()["error"]["code"] == "not_authenticated"
        checked += 1
    assert checked >= 15  # guards against the route list silently emptying


# --- IDOR --------------------------------------------------------------------


async def _upload(client: httpx.AsyncClient, module_id: str, path: Path, name: str) -> str:
    response = await client.post(
        "/api/v1/documents",
        params={
            "module_id": module_id,
            "filename": name,
            "source_tier": "university",
            "material_kind": "lecture",
        },
        content=path.read_bytes(),
    )
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


async def _seed_owner(client: httpx.AsyncClient, tmp_path: Path) -> dict[str, str]:
    """Owner A's year, module, topic tree, documents, and trashed items."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    year = (
        await client.post(
            "/api/v1/years",
            json={"label": "2026/27", "start_date": "2026-09-21", "end_date": "2027-06-11"},
        )
    ).json()
    module = (
        await client.post(
            "/api/v1/modules",
            json={"academic_year_id": year["id"], "code": "MATH103", "title": "Linear Algebra"},
        )
    ).json()
    topic = (
        await client.post(f"/api/v1/modules/{module['id']}/topics", json={"title": "Matrices"})
    ).json()
    trashed = (
        await client.post(
            "/api/v1/modules",
            json={"academic_year_id": year["id"], "code": "MATH999", "title": "Old"},
        )
    ).json()
    await client.delete(f"/api/v1/modules/{trashed['id']}")
    deleted_topic = (
        await client.post(f"/api/v1/modules/{module['id']}/topics", json={"title": "Old topic"})
    ).json()
    await client.delete(f"/api/v1/topics/{deleted_topic['id']}")
    document = await _upload(client, module["id"], factories.pdf(tmp_path / "a.pdf"), "a.pdf")
    old_doc = await _upload(
        client, module["id"], factories.pdf(tmp_path / "b.pdf", ["other"]), "b.pdf"
    )
    await client.delete(f"/api/v1/documents/{old_doc}")
    return {
        "year": year["id"],
        "module": module["id"],
        "topic": topic["id"],
        "trashed_module": trashed["id"],
        "trashed_topic": deleted_topic["id"],
        "document": document,
        "trashed_document": old_doc,
        "page": "1",
    }


# (method, path template, json body) — every route that takes a resource id.
ATTACKS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("PATCH", "/api/v1/years/{year}", {"label": "pwned"}),
    ("POST", "/api/v1/years/{year}/make-current", None),
    ("DELETE", "/api/v1/years/{year}", None),
    ("GET", "/api/v1/modules/{module}", None),
    ("PATCH", "/api/v1/modules/{module}", {"title": "pwned"}),
    ("DELETE", "/api/v1/modules/{module}", None),
    ("POST", "/api/v1/modules/{trashed_module}/restore", None),
    ("GET", "/api/v1/modules/{module}/topics", None),
    ("POST", "/api/v1/modules/{module}/topics", {"title": "pwned"}),
    ("PATCH", "/api/v1/topics/{topic}", {"title": "pwned"}),
    ("POST", "/api/v1/topics/{topic}/move", {"parent_id": None, "position": 0}),
    ("DELETE", "/api/v1/topics/{topic}", None),
    ("POST", "/api/v1/topics/{trashed_topic}/restore", None),
    ("POST", "/api/v1/modules", {"academic_year_id": "{year}", "code": "X1", "title": "pwned"}),
    ("GET", "/api/v1/documents/{document}", None),
    ("PATCH", "/api/v1/documents/{document}", {"week": 1}),
    ("DELETE", "/api/v1/documents/{document}", None),
    ("POST", "/api/v1/documents/{document}/reprocess", None),
    ("POST", "/api/v1/documents/{trashed_document}/restore", None),
    ("GET", "/api/v1/documents/{document}/events", None),
    ("GET", "/api/v1/documents/{document}/file", None),
    ("GET", "/api/v1/documents/{document}/pages", None),
    ("PUT", "/api/v1/documents/{document}/pages/{page}", {"markdown": "pwned"}),
    ("POST", "/api/v1/documents/{document}/pages/{page}/retranscribe", None),
    ("GET", "/api/v1/documents/{document}/pages/{page}/preview", None),
]


def test_attack_list_covers_every_id_route(app: FastAPI) -> None:
    id_routes = {(m, p) for m, p in _routes(app) if "{" in p}
    attacked = {(m, re.sub(r"\{(\w+)\}", "{x}", p)) for m, p, _ in ATTACKS}
    normalised = {(m, re.sub(r"\{(\w+)\}", "{x}", p)) for m, p in id_routes}
    assert normalised <= attacked


async def test_other_users_resources_are_invisible(
    db_app: FastAPI, db: AsyncSession, tmp_path: Path
) -> None:
    owner = await make_user(db, "a@example.com", "A")
    intruder = await make_user(db, "b@example.com", "B")
    async with signed_in(db_app, owner) as a, signed_in(db_app, intruder, ip="192.0.2.5") as b:
        ids = await _seed_owner(a, tmp_path)
        before_tree = (await a.get(f"/api/v1/modules/{ids['module']}/topics")).json()
        before_years = (await a.get("/api/v1/years")).json()
        before_trash = (await a.get("/api/v1/trash")).json()

        for method, template, body in ATTACKS:
            url = template.format(**ids)
            payload = (
                {k: (v.format(**ids) if isinstance(v, str) else v) for k, v in body.items()}
                if body
                else None
            )
            response = await b.request(method, url, json=payload)
            assert response.status_code == 404, f"{method} {url} -> {response.status_code}"

        # B's listings contain none of A's data.
        assert (await b.get("/api/v1/years")).json() == []
        assert (await b.get("/api/v1/modules?status=all")).json() == []
        assert (await b.get("/api/v1/trash")).json()["modules"] == []
        assert (await b.get("/api/v1/documents")).json() == []
        # Uploading into A's module is refused too.
        upload = await b.post(
            "/api/v1/documents",
            params={
                "module_id": ids["module"],
                "filename": "x.pdf",
                "source_tier": "own",
                "material_kind": "notes",
            },
            content=factories.pdf(tmp_path / "c.pdf", ["intruder"]).read_bytes(),
        )
        assert upload.status_code == 404

        # A's data is untouched.
        assert (await a.get(f"/api/v1/modules/{ids['module']}/topics")).json() == before_tree
        assert (await a.get("/api/v1/years")).json() == before_years
        assert (await a.get("/api/v1/trash")).json() == before_trash


async def test_cannot_attach_a_topic_to_another_users_parent(
    db_app: FastAPI, db: AsyncSession, tmp_path: Path
) -> None:
    owner = await make_user(db, "a@example.com", "A")
    intruder = await make_user(db, "b@example.com", "B")
    async with signed_in(db_app, owner) as a, signed_in(db_app, intruder, ip="192.0.2.5") as b:
        a_ids = await _seed_owner(a, tmp_path / "a")
        b_ids = await _seed_owner(b, tmp_path / "b")
        create = await b.post(
            f"/api/v1/modules/{b_ids['module']}/topics",
            json={"title": "x", "parent_id": a_ids["topic"]},
        )
        move = await b.post(
            f"/api/v1/topics/{b_ids['topic']}/move",
            json={"parent_id": a_ids["topic"], "position": 0},
        )
    assert create.status_code == move.status_code == 404
