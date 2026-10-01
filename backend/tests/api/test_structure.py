"""Years, modules, the topic tree and the trash."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog
from tests.support import make_user, signed_in

pytestmark = pytest.mark.db


@pytest.fixture
async def client(db_app: FastAPI, db: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    async with signed_in(db_app, await make_user(db)) as c:
        yield c


async def _year(client: httpx.AsyncClient, label: str = "2026/27", **extra: Any) -> dict[str, Any]:
    start = f"20{label[2:4]}-09-21"
    end = f"20{int(label[2:4]) + 1}-06-11"
    response = await client.post(
        "/api/v1/years", json={"label": label, "start_date": start, "end_date": end, **extra}
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _module(
    client: httpx.AsyncClient, year_id: str, code: str = "MATH103", **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/modules",
        json={"academic_year_id": year_id, "code": code, "title": "Linear Algebra", **extra},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _topic(
    client: httpx.AsyncClient, module_id: str, title: str, parent_id: str | None = None
) -> str:
    response = await client.post(
        f"/api/v1/modules/{module_id}/topics", json={"title": title, "parent_id": parent_id}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _tree(client: httpx.AsyncClient, module_id: str) -> list[Any]:
    """The tree as nested (title, [children]) tuples, for readable asserts."""

    def shape(nodes: list[dict[str, Any]]) -> list[Any]:
        return [(n["title"], shape(n["children"])) if n["children"] else n["title"] for n in nodes]

    response = await client.get(f"/api/v1/modules/{module_id}/topics")
    assert response.status_code == 200
    return shape(response.json())


# --- years -------------------------------------------------------------------


async def test_first_year_becomes_current_and_switching_is_exclusive(
    client: httpx.AsyncClient,
) -> None:
    first = await _year(client, "2026/27")
    second = await _year(client, "2027/28")
    assert first["is_current"] and not second["is_current"]

    await client.post(f"/api/v1/years/{second['id']}/make-current")
    years = {y["label"]: y["is_current"] for y in (await client.get("/api/v1/years")).json()}
    assert years == {"2026/27": False, "2027/28": True}


async def test_year_validation(client: httpx.AsyncClient) -> None:
    await _year(client, "2026/27")
    duplicate = await client.post(
        "/api/v1/years",
        json={"label": "2026/27", "start_date": "2026-09-01", "end_date": "2027-06-01"},
    )
    backwards = await client.post(
        "/api/v1/years",
        json={"label": "x", "start_date": "2027-06-01", "end_date": "2026-09-01"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "year_label_taken"
    assert backwards.status_code == 422


async def test_year_with_modules_cannot_be_deleted(client: httpx.AsyncClient) -> None:
    year = await _year(client)
    module = await _module(client, year["id"])
    await client.delete(f"/api/v1/modules/{module['id']}")  # trashed still counts

    blocked = await client.delete(f"/api/v1/years/{year['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "year_not_empty"

    empty = await _year(client, "2027/28")
    assert (await client.delete(f"/api/v1/years/{empty['id']}")).status_code == 204


# --- modules -----------------------------------------------------------------


async def test_module_codes_are_normalised_and_unique_per_year(client: httpx.AsyncClient) -> None:
    year = await _year(client)
    module = await _module(client, year["id"], code=" math103 ", colour="#AABBCC")
    assert module["code"] == "MATH103"
    assert module["colour"] == "#aabbcc"

    clash = await client.post(
        "/api/v1/modules",
        json={"academic_year_id": year["id"], "code": "MATH103", "title": "Again"},
    )
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "module_code_taken"

    other_year = await _year(client, "2027/28")
    assert (await _module(client, other_year["id"], code="MATH103"))["code"] == "MATH103"


async def test_archive_and_list_filters(client: httpx.AsyncClient) -> None:
    year = await _year(client)
    keep = await _module(client, year["id"], code="MATH101")
    old = await _module(client, year["id"], code="MATH103")
    await client.patch(f"/api/v1/modules/{old['id']}", json={"status": "archived"})

    def codes(response: httpx.Response) -> list[str]:
        return [m["code"] for m in response.json()]

    assert codes(await client.get("/api/v1/modules")) == [keep["code"]]
    assert codes(await client.get("/api/v1/modules?status=archived")) == ["MATH103"]
    assert codes(await client.get("/api/v1/modules?status=all")) == ["MATH101", "MATH103"]
    other_year = await _year(client, "2027/28")
    assert codes(await client.get(f"/api/v1/modules?year_id={other_year['id']}")) == []


async def test_module_patch_semantics(client: httpx.AsyncClient) -> None:
    year = await _year(client)
    module = await _module(client, year["id"], subject_tag="Mathematics", credits=15)
    url = f"/api/v1/modules/{module['id']}"

    cleared = await client.patch(url, json={"subject_tag": None})
    assert cleared.json()["subject_tag"] is None
    assert cleared.json()["credits"] == 15  # omitted fields are untouched
    assert (await client.patch(url, json={"title": None})).status_code == 422
    assert (await client.patch(url, json={"credits": 500})).status_code == 422
    assert (await client.patch(url, json={"unknown": 1})).status_code == 422


async def test_module_trash_and_restore(client: httpx.AsyncClient, db: AsyncSession) -> None:
    year = await _year(client)
    module = await _module(client, year["id"])
    await _topic(client, module["id"], "Matrices")

    assert (await client.delete(f"/api/v1/modules/{module['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/modules/{module['id']}")).status_code == 404
    trash = (await client.get("/api/v1/trash")).json()
    assert [m["code"] for m in trash["modules"]] == ["MATH103"]
    assert trash["retention_days"] == 30

    restored = await client.post(f"/api/v1/modules/{module['id']}/restore")
    assert restored.status_code == 200
    assert await _tree(client, module["id"]) == ["Matrices"]  # topics come back with it

    actions = (await db.scalars(select(AuditLog.action).order_by(AuditLog.id))).all()
    assert actions[-2:] == ["module_deleted", "module_restored"]


async def test_restore_refused_when_code_was_reused(client: httpx.AsyncClient) -> None:
    year = await _year(client)
    old = await _module(client, year["id"])
    await client.delete(f"/api/v1/modules/{old['id']}")
    await _module(client, year["id"])  # same code, now allowed

    response = await client.post(f"/api/v1/modules/{old['id']}/restore")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "module_code_taken"


# --- topics ------------------------------------------------------------------


async def test_topic_tree_nests_and_orders(client: httpx.AsyncClient) -> None:
    module = await _module(client, (await _year(client))["id"])
    integration = await _topic(client, module["id"], "Integration")
    await _topic(client, module["id"], "Series")
    await _topic(client, module["id"], "Integration by Parts", integration)
    await _topic(client, module["id"], "Substitution", integration)

    assert await _tree(client, module["id"]) == [
        ("Integration", ["Integration by Parts", "Substitution"]),
        "Series",
    ]


async def test_move_reorders_and_reparents(client: httpx.AsyncClient) -> None:
    module = await _module(client, (await _year(client))["id"])
    a = await _topic(client, module["id"], "A")
    b = await _topic(client, module["id"], "B")
    c = await _topic(client, module["id"], "C")

    await client.post(f"/api/v1/topics/{c}/move", json={"parent_id": None, "position": 0})
    assert await _tree(client, module["id"]) == ["C", "A", "B"]

    await client.post(f"/api/v1/topics/{b}/move", json={"parent_id": a, "position": 99})
    assert await _tree(client, module["id"]) == ["C", ("A", ["B"])]

    positions = [
        n["position"] for n in (await client.get(f"/api/v1/modules/{module['id']}/topics")).json()
    ]
    assert positions == [0, 1]  # no gaps left behind


async def test_move_cannot_create_a_cycle(client: httpx.AsyncClient) -> None:
    module = await _module(client, (await _year(client))["id"])
    parent = await _topic(client, module["id"], "Parent")
    child = await _topic(client, module["id"], "Child", parent)
    grandchild = await _topic(client, module["id"], "Grandchild", child)

    for target in (parent, grandchild):
        response = await client.post(
            f"/api/v1/topics/{parent}/move", json={"parent_id": target, "position": 0}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_move"


async def test_topics_cannot_cross_modules(client: httpx.AsyncClient) -> None:
    year = (await _year(client))["id"]
    first = await _module(client, year, code="MATH101")
    second = await _module(client, year, code="MATH103")
    foreign_parent = await _topic(client, first["id"], "Calculus")

    response = await client.post(
        f"/api/v1/modules/{second['id']}/topics",
        json={"title": "x", "parent_id": foreign_parent},
    )
    assert response.status_code == 404


async def test_deleting_a_topic_trashes_its_subtree_and_restore_brings_it_back(
    client: httpx.AsyncClient,
) -> None:
    module = await _module(client, (await _year(client))["id"])
    integration = await _topic(client, module["id"], "Integration")
    parts = await _topic(client, module["id"], "Integration by Parts", integration)
    await _topic(client, module["id"], "Tabular method", parts)
    await _topic(client, module["id"], "Series")

    assert (await client.delete(f"/api/v1/topics/{integration}")).status_code == 204
    assert await _tree(client, module["id"]) == ["Series"]
    trash = (await client.get("/api/v1/trash")).json()
    assert [t["title"] for t in trash["topics"]] == ["Integration"]  # one restorable unit

    # A child cannot be restored on its own while its parent is in the trash.
    alone = await client.post(f"/api/v1/topics/{parts}/restore")
    assert alone.status_code == 409
    assert alone.json()["error"]["code"] == "parent_deleted"

    restored = await client.post(f"/api/v1/topics/{integration}/restore")
    assert restored.status_code == 200
    assert await _tree(client, module["id"]) == [
        "Series",
        ("Integration", [("Integration by Parts", ["Tabular method"])]),
    ]


async def test_separately_deleted_child_stays_deleted_when_parent_is_restored(
    client: httpx.AsyncClient,
) -> None:
    module = await _module(client, (await _year(client))["id"])
    parent = await _topic(client, module["id"], "Parent")
    early = await _topic(client, module["id"], "Deleted earlier", parent)
    await _topic(client, module["id"], "Kept", parent)

    await client.delete(f"/api/v1/topics/{early}")
    await client.delete(f"/api/v1/topics/{parent}")
    blocked = await client.post(f"/api/v1/topics/{early}/restore")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "parent_deleted"

    await client.post(f"/api/v1/topics/{parent}/restore")
    assert await _tree(client, module["id"]) == [("Parent", ["Kept"])]
    assert (await client.post(f"/api/v1/topics/{early}/restore")).status_code == 200
    assert await _tree(client, module["id"]) == [("Parent", ["Kept", "Deleted earlier"])]


async def test_topic_update_validation(client: httpx.AsyncClient) -> None:
    module = await _module(client, (await _year(client))["id"])
    topic = await _topic(client, module["id"], "Matrices")
    url = f"/api/v1/topics/{topic}"

    ok = await client.patch(url, json={"title": "  Determinants ", "importance": 5})
    assert ok.json()["title"] == "Determinants"
    assert ok.json()["importance"] == 5
    for bad in ({"title": None}, {"title": "   "}, {"importance": 6}):
        assert (await client.patch(url, json=bad)).status_code == 422
