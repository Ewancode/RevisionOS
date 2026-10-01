"""Upload -> process -> pages, end to end, with the worker's job run in-process."""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import ClaudeClient
from app.core.config import get_config
from app.ingestion.pipeline import Deps, process_document, retranscribe_page
from app.models import AIUsage, AuditLog
from tests import factories
from tests.fakes import FakeAnthropic, RecordingQueue, transcription
from tests.support import make_user, signed_in

pytestmark = pytest.mark.db


@pytest.fixture
async def client(db_app: FastAPI, db: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    async with signed_in(db_app, await make_user(db)) as c:
        yield c


@pytest.fixture
async def module_id(client: httpx.AsyncClient) -> str:
    year = (
        await client.post(
            "/api/v1/years",
            json={"label": "2026/27", "start_date": "2026-09-21", "end_date": "2027-06-11"},
        )
    ).json()
    module = await client.post(
        "/api/v1/modules",
        json={"academic_year_id": year["id"], "code": "MATH103", "title": "Linear Algebra"},
    )
    return str(module.json()["id"])


async def _upload(
    client: httpx.AsyncClient, module_id: str, path: Path, filename: str, **params: Any
) -> httpx.Response:
    query = {
        "module_id": module_id,
        "filename": filename,
        "source_tier": "university",
        "material_kind": "lecture",
        **params,
    }
    return await client.post("/api/v1/documents", params=query, content=path.read_bytes())


async def _process(deps: Deps, queue: RecordingQueue) -> None:
    """Run every queued job the way the worker would."""
    while queue.jobs:
        name, args = queue.jobs.pop(0)
        if name == "process_document":
            await process_document(deps, uuid.UUID(args[0]))
        elif name == "retranscribe_page":
            await retranscribe_page(deps, uuid.UUID(args[0]), args[1])


async def _pages(client: httpx.AsyncClient, doc_id: str) -> list[dict[str, Any]]:
    response = await client.get(f"/api/v1/documents/{doc_id}/pages")
    assert response.status_code == 200
    return list(response.json())


async def test_upload_queues_processing_and_pages_appear(
    client: httpx.AsyncClient, module_id: str, deps: Deps, queue: RecordingQueue, tmp_path: Path
) -> None:
    path = factories.pdf(tmp_path / "x", [factories.PROSE, "Second page text " * 5])
    response = await _upload(client, module_id, path, "../../Lecture 5.pdf", week=5)

    assert response.status_code == 202
    doc = response.json()
    assert doc["original_filename"] == "Lecture 5.pdf"  # path part dropped
    assert (doc["status"], doc["page_count"], doc["week"]) == ("queued", 2, 5)
    assert queue.jobs == [("process_document", (doc["id"],))]

    await _process(deps, queue)
    after = (await client.get(f"/api/v1/documents/{doc['id']}")).json()
    assert (after["status"], after["progress"]) == ("ready", 100)
    pages = await _pages(client, doc["id"])
    assert [p["page_no"] for p in pages] == [1, 2]
    assert "product rule" in pages[0]["markdown"]
    assert {p["extraction_method"] for p in pages} == {"text"}


async def test_only_damaged_pages_are_sent_to_claude(
    client: httpx.AsyncClient,
    module_id: str,
    deps: Deps,
    queue: RecordingQueue,
    fake_claude: FakeAnthropic,
    db: AsyncSession,
    tmp_path: Path,
) -> None:
    answer = (
        "## Vectors\n\n"
        "$$\\mathbf{u} \\times \\mathbf{v} = \\begin{pmatrix} 1 \\\\ 2 \\end{pmatrix}$$"
    )
    fake_claude.respond = lambda _: transcription(answer)
    response = await _upload(
        client, module_id, factories.damaged_maths_pdf(tmp_path / "x"), "v.pdf"
    )
    await _process(deps, queue)

    prose, maths = await _pages(client, response.json()["id"])
    assert len(fake_claude.requests) == 1  # page 1 never left the machine
    assert prose["extraction_method"] == "text"
    assert maths["extraction_method"] == "vision"
    assert "\\begin{pmatrix}" in maths["markdown"]
    assert maths["maths_damage_score"] >= get_config().platform.ingestion.maths_damage.threshold
    assert len((await db.scalars(select(AIUsage))).all()) == 1


async def test_low_confidence_transcriptions_are_flagged(
    client: httpx.AsyncClient,
    module_id: str,
    deps: Deps,
    queue: RecordingQueue,
    fake_claude: FakeAnthropic,
    tmp_path: Path,
) -> None:
    fake_claude.respond = lambda _: transcription("$x_? = 1$", "low", "subscript unclear")
    response = await _upload(
        client, module_id, factories.damaged_maths_pdf(tmp_path / "x"), "v.pdf"
    )
    await _process(deps, queue)
    _, maths = await _pages(client, response.json()["id"])
    assert maths["needs_review"] is True
    assert maths["review_note"] == "subscript unclear"


async def test_without_claude_damaged_pages_are_kept_and_flagged(
    client: httpx.AsyncClient,
    module_id: str,
    deps: Deps,
    queue: RecordingQueue,
    tmp_path: Path,
) -> None:
    deps.claude = ClaudeClient(None, get_config().ai)
    response = await _upload(client, module_id, factories.scanned_pdf(tmp_path / "x"), "scan.pdf")
    await _process(deps, queue)

    doc = (await client.get(f"/api/v1/documents/{response.json()['id']}")).json()
    assert doc["status"] == "ready"  # one bad page never fails the document
    scanned, blank = await _pages(client, doc["id"])
    assert scanned["extraction_method"] == "unreadable"
    assert scanned["needs_review"] is True
    assert "not configured" in scanned["review_note"]
    assert blank["needs_review"] is False


async def test_corrections_survive_reprocessing(
    client: httpx.AsyncClient,
    module_id: str,
    deps: Deps,
    queue: RecordingQueue,
    fake_claude: FakeAnthropic,
    tmp_path: Path,
) -> None:
    response = await _upload(
        client, module_id, factories.damaged_maths_pdf(tmp_path / "x"), "v.pdf"
    )
    doc_id = response.json()["id"]
    await _process(deps, queue)

    fixed = await client.put(
        f"/api/v1/documents/{doc_id}/pages/2", json={"markdown": "$$a^2+b^2=c^2$$"}
    )
    assert fixed.json()["extraction_method"] == "corrected"

    assert (await client.post(f"/api/v1/documents/{doc_id}/reprocess")).status_code == 200
    await _process(deps, queue)
    _, maths = await _pages(client, doc_id)
    assert maths["markdown"] == "$$a^2+b^2=c^2$$"
    assert len(fake_claude.requests) == 1  # the corrected page was not re-sent


async def test_retranscribing_one_page(
    client: httpx.AsyncClient,
    module_id: str,
    deps: Deps,
    queue: RecordingQueue,
    fake_claude: FakeAnthropic,
    tmp_path: Path,
) -> None:
    response = await _upload(client, module_id, factories.pdf(tmp_path / "x"), "p.pdf")
    doc_id = response.json()["id"]
    await _process(deps, queue)
    assert fake_claude.requests == []

    fake_claude.respond = lambda _: transcription("# Redone")
    accepted = await client.post(f"/api/v1/documents/{doc_id}/pages/1/retranscribe")
    assert accepted.status_code == 202
    await _process(deps, queue)
    [page] = await _pages(client, doc_id)
    assert (page["markdown"], page["extraction_method"]) == ("# Redone", "vision")


async def test_photos_are_transcribed(
    client: httpx.AsyncClient,
    module_id: str,
    deps: Deps,
    queue: RecordingQueue,
    fake_claude: FakeAnthropic,
    tmp_path: Path,
) -> None:
    fake_claude.respond = lambda _: transcription("Handwritten: $\\int_0^1 x\\,dx = \\tfrac12$")
    response = await _upload(
        client, module_id, factories.jpeg_with_gps(tmp_path / "x"), "IMG_1.HEIC.jpg"
    )
    await _process(deps, queue)
    [page] = await _pages(client, response.json()["id"])
    assert page["extraction_method"] == "vision"
    image = fake_claude.requests[0]["messages"][0]["content"][0]
    assert image["source"]["media_type"] == "image/jpeg"


async def test_duplicates_are_refused_with_a_pointer(
    client: httpx.AsyncClient, module_id: str, tmp_path: Path
) -> None:
    path = factories.pdf(tmp_path / "x")
    first = await _upload(client, module_id, path, "Lecture 1.pdf")
    second = await _upload(client, module_id, path, "copy.pdf")
    assert second.status_code == 409
    error = second.json()["error"]
    assert error["code"] == "duplicate_upload"
    assert "Lecture 1.pdf" in error["message"]
    assert error["details"] == {"document_id": first.json()["id"]}


async def test_invalid_uploads_are_refused(
    client: httpx.AsyncClient, module_id: str, queue: RecordingQueue, tmp_path: Path
) -> None:
    disguised = await _upload(client, module_id, factories.pdf(tmp_path / "x"), "photo.png")
    assert disguised.json()["error"]["code"] == "type_mismatch"

    huge = await client.post(
        "/api/v1/documents",
        params={
            "module_id": module_id,
            "filename": "a.pdf",
            "source_tier": "own",
            "material_kind": "notes",
        },
        content=b"x",
        headers={"Content-Length": str(10**12)},
    )
    assert huge.status_code == 413
    assert queue.jobs == []


async def test_topic_must_belong_to_the_module(
    client: httpx.AsyncClient, module_id: str, tmp_path: Path
) -> None:
    response = await _upload(
        client, module_id, factories.pdf(tmp_path / "x"), "a.pdf", topic_id=str(uuid.uuid4())
    )
    assert response.status_code == 404


async def test_preview_download_and_events(
    client: httpx.AsyncClient, module_id: str, deps: Deps, queue: RecordingQueue, tmp_path: Path
) -> None:
    path = factories.pdf(tmp_path / "x")
    doc_id = (await _upload(client, module_id, path, "Lecture 5.pdf")).json()["id"]
    await _process(deps, queue)

    preview = await client.get(f"/api/v1/documents/{doc_id}/pages/1/preview")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    assert preview.content.startswith(b"\x89PNG")

    download = await client.get(f"/api/v1/documents/{doc_id}/file")
    assert download.content == path.read_bytes()
    assert download.headers["content-disposition"].startswith("attachment;")
    assert download.headers["x-content-type-options"] == "nosniff"

    events = await client.get(f"/api/v1/documents/{doc_id}/events")
    assert events.headers["content-type"].startswith("text/event-stream")
    assert '"status":"ready"' in events.text


async def test_delete_restore_and_trash(
    client: httpx.AsyncClient, module_id: str, db: AsyncSession, tmp_path: Path
) -> None:
    doc_id = (await _upload(client, module_id, factories.pdf(tmp_path / "x"), "a.pdf")).json()["id"]
    assert (await client.delete(f"/api/v1/documents/{doc_id}")).status_code == 204
    assert (await client.get(f"/api/v1/documents/{doc_id}")).status_code == 404
    trash = (await client.get("/api/v1/trash")).json()
    assert [d["original_filename"] for d in trash["documents"]] == ["a.pdf"]

    assert (await client.post(f"/api/v1/documents/{doc_id}/restore")).status_code == 200
    actions = (await db.scalars(select(AuditLog.action).order_by(AuditLog.id))).all()
    assert actions[-2:] == ["document_deleted", "document_restored"]


async def test_budget_endpoint(client: httpx.AsyncClient) -> None:
    budget = (await client.get("/api/v1/ai/budget")).json()
    assert budget["currency"] == "GBP"
    assert budget["monthly_cap"] == 10.0
    assert budget["spent_this_month"] == 0
    assert budget["configured"] is True


async def test_control_characters_from_broken_fonts_are_stripped(
    client: httpx.AsyncClient,
    module_id: str,
    deps: Deps,
    queue: RecordingQueue,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Regression: a real lecture PDF's font encoding produced NUL and other
    control characters, which PostgreSQL refuses, failing the whole document."""
    from app.ingestion import pipeline
    from app.ingestion.extract import ExtractedPage

    garbled = "Z 1" + chr(0) + "0 2" + chr(0x1B) + "x" + chr(0x15) + " dx\tok\nline"
    monkeypatch.setattr(pipeline, "extract", lambda *_: [ExtractedPage(1, garbled, 0.0, None)])
    doc_id = (await _upload(client, module_id, factories.pdf(tmp_path / "x"), "a.pdf")).json()["id"]
    await _process(deps, queue)

    assert (await client.get(f"/api/v1/documents/{doc_id}")).json()["status"] == "ready"
    [page] = await _pages(client, doc_id)
    assert page["markdown"] == "Z 10 2x dx\tok\nline"


async def test_nul_characters_in_input_are_rejected_not_crashed_on(
    client: httpx.AsyncClient, module_id: str, deps: Deps, queue: RecordingQueue, tmp_path: Path
) -> None:
    doc_id = (await _upload(client, module_id, factories.pdf(tmp_path / "x"), "a.pdf")).json()["id"]
    await _process(deps, queue)
    response = await client.put(
        f"/api/v1/documents/{doc_id}/pages/1", json={"markdown": "bad" + chr(0) + "text"}
    )
    assert response.status_code == 422
    rename = await client.patch(f"/api/v1/modules/{module_id}", json={"title": "x" + chr(0)})
    assert rename.status_code == 422
