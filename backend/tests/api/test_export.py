"""The export and restore API, with the worker jobs run in-process."""

import io
import uuid
import zipfile
from collections.abc import AsyncIterator
from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.export.jobs import run_export, run_restore
from app.ingestion.pipeline import Deps
from app.models import DataJob, User
from app.services.exports import expire_exports
from app.storage.local import LocalStorage
from tests.export_support import seed_everything
from tests.fakes import RecordingQueue
from tests.support import make_user, signed_in


@pytest.fixture
async def alice(db: AsyncSession, storage: LocalStorage) -> User:
    user = await make_user(db, "alice@example.com")
    await seed_everything(db, storage, user)
    return user


@pytest.fixture
async def client(db_app: FastAPI, alice: User) -> AsyncIterator[httpx.AsyncClient]:
    async with signed_in(db_app, alice) as c:
        yield c


async def exported(client: httpx.AsyncClient, queue: RecordingQueue, deps: Deps) -> bytes:
    response = await client.post("/api/v1/export")
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["status"] == "queued" and queue.jobs[-1] == ("run_export", (job["id"],))
    await run_export(deps, uuid.UUID(job["id"]))
    done = (await client.get(f"/api/v1/export/{job['id']}")).json()
    assert done["status"] == "done" and done["counts"]["questions"] == 1
    assert done["expires_at"] is not None
    file = await client.get(f"/api/v1/export/{job['id']}/file")
    assert file.status_code == 200
    assert file.headers["content-type"] == "application/zip"
    assert "attachment" in file.headers["content-disposition"]
    return file.content


async def test_export_then_restore_into_a_new_account(
    db_app: FastAPI, client: httpx.AsyncClient, queue: RecordingQueue, deps: Deps, db: AsyncSession
) -> None:
    archive = await exported(client, queue, deps)
    assert zipfile.ZipFile(io.BytesIO(archive)).testzip() is None

    bob = await make_user(db, "bob@example.com")
    async with signed_in(db_app, bob) as bob_client:
        response = await bob_client.post("/api/v1/export/restore", content=archive)
        assert response.status_code == 202, response.text
        job = response.json()
        assert queue.jobs[-1] == ("run_restore", (job["id"],))
        reindex: list[str] = []

        async def enqueue(function: str, arg: str) -> None:
            reindex.append(arg)

        await run_restore(deps, uuid.UUID(job["id"]), enqueue)
        done = (await bob_client.get(f"/api/v1/export/{job['id']}")).json()
        assert done["status"] == "done", done
        assert done["counts"]["modules"] == 1 and done["counts"]["files"] == 3
        assert reindex == []
        modules = (await bob_client.get("/api/v1/modules")).json()
        assert [m["code"] for m in modules] == ["MATH101"]
        # The uploaded archive is not kept once restored.
        assert not any("imports/" in k for k in await deps.storage.list_keys(f"users/{bob.id}/"))

        # Restoring again is refused: the account is no longer empty.
        again = await bob_client.post("/api/v1/export/restore", content=archive)
        assert again.status_code == 409 and again.json()["error"]["code"] == "account_not_empty"


async def test_exports_are_private_and_one_at_a_time(
    db_app: FastAPI, client: httpx.AsyncClient, db: AsyncSession
) -> None:
    job = (await client.post("/api/v1/export")).json()
    busy = await client.post("/api/v1/export")
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "export_running"
    mallory = await make_user(db, "mallory@example.com")
    async with signed_in(db_app, mallory) as other:
        assert (await other.get(f"/api/v1/export/{job['id']}")).status_code == 404
        assert (await other.get(f"/api/v1/export/{job['id']}/file")).status_code == 404
        assert (await other.get("/api/v1/export")).json() == []


async def test_a_file_that_is_not_an_export_is_refused(db_app: FastAPI, db: AsyncSession) -> None:
    bob = await make_user(db, "bob@example.com")
    async with signed_in(db_app, bob) as c:
        response = await c.post("/api/v1/export/restore", content=b"not a zip")
        assert response.status_code == 422 and response.json()["error"]["code"] == "bad_archive"
        assert (await c.get("/api/v1/export")).json() == []


async def test_old_exports_expire(
    client: httpx.AsyncClient, queue: RecordingQueue, deps: Deps, db: AsyncSession
) -> None:
    await exported(client, queue, deps)
    job_id = queue.jobs[-1][1][0]
    await db.execute(
        update(DataJob)
        .where(DataJob.id == uuid.UUID(job_id))
        .values(created_at=DataJob.created_at - timedelta(days=8))
    )
    await db.commit()
    assert await expire_exports(db, deps.storage, keep_days=7) == 1
    gone = await client.get(f"/api/v1/export/{job_id}/file")
    assert gone.status_code == 410 and gone.json()["error"]["code"] == "export_expired"
    assert (await client.get(f"/api/v1/export/{job_id}")).json()["expires_at"] is None
