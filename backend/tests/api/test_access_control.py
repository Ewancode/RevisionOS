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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AvailabilityOverride,
    Draft,
    Exam,
    Flashcard,
    Material,
    MaterialVersion,
    Notification,
    PendingAction,
    Question,
    QuestionAttempt,
    Quiz,
    QuizAttempt,
    QuizItem,
    StudySession,
    User,
)
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
    conversation = (
        await client.post("/api/v1/conversations", json={"module_id": module["id"]})
    ).json()
    return {
        "year": year["id"],
        "module": module["id"],
        "topic": topic["id"],
        "trashed_module": trashed["id"],
        "trashed_topic": deleted_topic["id"],
        "document": document,
        "trashed_document": old_doc,
        "page": "1",
        "conversation": conversation["id"],
    }


async def _seed_pending_action(db: AsyncSession, owner: User, ids: dict[str, str]) -> None:
    """A delete request Claude made for A (tools create these, not the API)."""
    action = PendingAction(
        id=uuid.uuid4(),
        user_id=owner.id,
        conversation_id=uuid.UUID(ids["conversation"]),
        action="delete_document",
        target_id=uuid.UUID(ids["document"]),
        preview="Delete a.pdf?",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db.add(action)
    await db.commit()
    ids["action"] = str(action.id)


async def _seed_practice(db: AsyncSession, owner: User, ids: dict[str, str]) -> None:
    """A's draft, material with two versions, trashed material, question,
    flashcards, quiz, attempt and answer (made directly: no Claude needed)."""
    module = uuid.UUID(ids["module"])
    user = owner.id
    now = datetime.now(UTC)
    draft = Draft(
        id=uuid.uuid4(), user_id=user, module_id=module, kind="questions", request={},
        status="ready", payload={"items": [], "passages": []},
    )  # fmt: skip
    material = Material(
        id=uuid.uuid4(), user_id=user, module_id=module, title="Guide", kind="guide", origin="user"
    )
    trashed = Material(
        id=uuid.uuid4(), user_id=user, module_id=module, title="Old", kind="guide",
        origin="user", deleted_at=now,
    )  # fmt: skip
    db.add_all([draft, material, trashed])
    await db.flush()
    old = MaterialVersion(
        id=uuid.uuid4(), material_id=material.id, user_id=user, version_no=1,
        content_md="v1", created_by="user",
    )  # fmt: skip
    new = MaterialVersion(
        id=uuid.uuid4(), material_id=material.id, user_id=user, version_no=2,
        content_md="v2", created_by="user",
    )  # fmt: skip
    db.add_all([old, new])
    await db.flush()
    material.current_version_id = new.id
    question = Question(
        id=uuid.uuid4(), user_id=user, module_id=module, type="multiple_choice",
        difficulty="easy", rating=1350, stem_md="2+2?", solution_md="4", origin="claude",
        answer_spec={"type": "multiple_choice", "options": ["3", "4"], "correct": 1},
    )  # fmt: skip
    card = Flashcard(
        id=uuid.uuid4(), user_id=user, module_id=module, front_md="f", back_md="b", origin="user"
    )
    old_card = Flashcard(
        id=uuid.uuid4(), user_id=user, module_id=module, front_md="o", back_md="b",
        origin="user", deleted_at=now,
    )  # fmt: skip
    quiz = Quiz(id=uuid.uuid4(), user_id=user, module_id=module, kind="practice", title="Q")
    db.add_all([question, card, old_card, quiz])
    await db.flush()
    attempt = QuizAttempt(id=uuid.uuid4(), user_id=user, quiz_id=quiz.id, mode="normal")
    db.add_all(
        [QuizItem(quiz_id=quiz.id, position=0, user_id=user, question_id=question.id), attempt]
    )
    await db.flush()
    answer = QuestionAttempt(
        id=uuid.uuid4(), user_id=user, quiz_attempt_id=attempt.id, question_id=question.id
    )
    db.add(answer)
    await db.commit()
    ids |= {
        "draft": str(draft.id),
        "material": str(material.id),
        "trashed_material": str(trashed.id),
        "version": str(new.id),
        "old_version": str(old.id),
        "question": str(question.id),
        "flashcard": str(card.id),
        "trashed_flashcard": str(old_card.id),
        "quiz": str(quiz.id),
        "attempt": str(attempt.id),
        "answer": str(answer.id),
    }


async def _seed_planner(db: AsyncSession, owner: User, ids: dict[str, str]) -> None:
    """A's exam, planned session and notification."""
    module = uuid.UUID(ids["module"])
    exam = Exam(
        id=uuid.uuid4(),
        user_id=owner.id,
        module_id=module,
        title="Final",
        starts_at=datetime.now(UTC) + timedelta(days=30),
        duration_minutes=120,
    )
    session = StudySession(
        id=uuid.uuid4(),
        user_id=owner.id,
        module_id=module,
        kind="topic",
        day=(datetime.now(UTC) + timedelta(days=2)).date(),
        minutes=45,
    )
    note = Notification(user_id=owner.id, kind="exam", title="t", dedupe_key="k")
    day = (datetime.now(UTC) + timedelta(days=3)).date()
    override = AvailabilityOverride(user_id=owner.id, day=day, minutes=30)
    db.add_all([exam, session, note, override])
    await db.commit()
    ids |= {
        "exam": str(exam.id),
        "session": str(session.id),
        "notification": str(note.id),
        "override_day": day.isoformat(),
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
    ("POST", "/api/v1/conversations", {"module_id": "{module}"}),
    ("GET", "/api/v1/conversations/{conversation}", None),
    ("DELETE", "/api/v1/conversations/{conversation}", None),
    ("POST", "/api/v1/conversations/{conversation}/messages", {"content": "pwned"}),
    ("POST", "/api/v1/pending-actions/{action}/confirm", None),
    ("POST", "/api/v1/pending-actions/{action}/cancel", None),
    # Phase 6: drafts, materials, the bank, flashcards, quizzes and attempts.
    ("POST", "/api/v1/drafts", {"module_id": "{module}", "kind": "questions"}),
    ("GET", "/api/v1/drafts/{draft}", None),
    ("POST", "/api/v1/drafts/{draft}/save", {"selected": []}),
    ("POST", "/api/v1/drafts/{draft}/regenerate", {"instructions": "x"}),
    ("POST", "/api/v1/drafts/{draft}/discard", None),
    ("POST", "/api/v1/materials", {"module_id": "{module}", "title": "x", "content_md": "x"}),
    ("GET", "/api/v1/materials/{material}", None),
    ("PATCH", "/api/v1/materials/{material}", {"title": "pwned"}),
    ("DELETE", "/api/v1/materials/{material}", None),
    ("POST", "/api/v1/materials/{trashed_material}/restore", None),
    ("POST", "/api/v1/materials/{material}/versions", {"content_md": "pwned"}),
    ("GET", "/api/v1/materials/{material}/versions/{version}", None),
    ("POST", "/api/v1/materials/{material}/versions/{version}/restore", None),
    ("DELETE", "/api/v1/materials/{material}/versions/{old_version}", None),
    (
        "GET",
        "/api/v1/materials/{material}/diff?from_version={old_version}&to_version={version}",
        None,
    ),
    ("PATCH", "/api/v1/questions/{question}", {"status": "retired"}),
    ("POST", "/api/v1/flashcards", {"module_id": "{module}", "front_md": "x", "back_md": "y"}),
    ("PATCH", "/api/v1/flashcards/{flashcard}", {"front_md": "pwned"}),
    ("DELETE", "/api/v1/flashcards/{flashcard}", None),
    ("POST", "/api/v1/flashcards/{trashed_flashcard}/restore", None),
    ("POST", "/api/v1/flashcards/{flashcard}/review", {"rating": 3}),
    # Phase 8: the planner.
    (
        "POST",
        "/api/v1/exams",
        {
            "module_id": "{module}",
            "title": "x",
            "starts_at": "2026-12-01T09:00:00Z",
            "duration_minutes": 60,
        },
    ),
    ("PATCH", "/api/v1/exams/{exam}", {"title": "pwned"}),
    ("DELETE", "/api/v1/exams/{exam}", None),
    ("PATCH", "/api/v1/sessions/{session}", {"day": "2030-01-01"}),
    ("POST", "/api/v1/sessions/{session}/status", {"status": "done"}),
    ("POST", "/api/v1/notifications/{notification}/read", None),
    ("DELETE", "/api/v1/availability/overrides/{override_day}", None),
    ("POST", "/api/v1/quizzes", {"module_id": "{module}"}),
    ("POST", "/api/v1/quizzes", {"module_id": "{module}", "question_ids": ["{question}"]}),
    ("POST", "/api/v1/quizzes/{quiz}/attempts", None),
    ("GET", "/api/v1/attempts/{attempt}", None),
    ("PUT", "/api/v1/attempts/{attempt}/responses/{question}", {"response": {"choice": 0}}),
    ("POST", "/api/v1/attempts/{attempt}/responses/{question}/photo?filename=a.png", None),
    ("POST", "/api/v1/attempts/{attempt}/submit", None),
    ("POST", "/api/v1/answers/{answer}/dispute", None),
    ("POST", "/api/v1/answers/{answer}/override", {"score": 1}),
]


def _fill(value: Any, ids: dict[str, str]) -> Any:
    """Put A's ids into a request body template, including inside lists."""
    if isinstance(value, str):
        return value.format(**ids)
    if isinstance(value, list):
        return [_fill(v, ids) for v in value]
    return value


def test_attack_list_covers_every_id_route(app: FastAPI) -> None:
    id_routes = {(m, p) for m, p in _routes(app) if "{" in p}
    attacked = {(m, re.sub(r"\{(\w+)\}", "{x}", p.split("?")[0])) for m, p, _ in ATTACKS}
    normalised = {(m, re.sub(r"\{(\w+)\}", "{x}", p)) for m, p in id_routes}
    assert normalised <= attacked


async def test_other_users_resources_are_invisible(
    db_app: FastAPI, db: AsyncSession, tmp_path: Path
) -> None:
    owner = await make_user(db, "a@example.com", "A")
    intruder = await make_user(db, "b@example.com", "B")
    async with signed_in(db_app, owner) as a, signed_in(db_app, intruder, ip="192.0.2.5") as b:
        ids = await _seed_owner(a, tmp_path)
        await _seed_pending_action(db, owner, ids)
        await _seed_practice(db, owner, ids)
        await _seed_planner(db, owner, ids)
        before_tree = (await a.get(f"/api/v1/modules/{ids['module']}/topics")).json()
        before_years = (await a.get("/api/v1/years")).json()
        before_trash = (await a.get("/api/v1/trash")).json()

        for method, template, body in ATTACKS:
            url = template.format(**ids)
            payload = {k: _fill(v, ids) for k, v in body.items()} if body else None
            response = await b.request(method, url, json=payload)
            assert response.status_code == 404, f"{method} {url} -> {response.status_code}"

        # B's listings contain none of A's data.
        assert (await b.get("/api/v1/years")).json() == []
        assert (await b.get("/api/v1/modules?status=all")).json() == []
        assert (await b.get("/api/v1/trash")).json()["modules"] == []
        assert (await b.get("/api/v1/documents")).json() == []
        assert (await b.get("/api/v1/conversations")).json() == []
        for listing in (
            "materials",
            "questions",
            "flashcards",
            "drafts",
            "attempts",
            "progress",
            "mistakes",
            "flashcards/due",
        ):
            response = await b.get(f"/api/v1/{listing}", params={"module_id": ids["module"]})
            assert response.status_code == 404, listing
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
        assert (await a.get(f"/api/v1/conversations/{ids['conversation']}")).status_code == 200
        action = await db.get(PendingAction, uuid.UUID(ids["action"]))
        assert action is not None
        await db.refresh(action)
        assert action.status == "pending"


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
