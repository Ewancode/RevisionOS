"""An account with at least one row in every exported table, and files in
storage, for export and restore tests. `test_every_table_is_covered` fails if
a new table is added without a row here, so round trips stay complete."""

import hashlib
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.db.base import Base
from app.models import User
from app.storage.base import answer_image_key, document_key, page_image_key
from app.storage.local import LocalStorage

NOW = datetime(2026, 10, 6, 9, tzinfo=UTC)
DIM = get_config().retrieval.embeddings.dimensions
MODEL = get_config().retrieval.embeddings.model
PDF = b"%PDF-1.7\n% pretend lecture\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n pretend page"


async def seed_everything(db: AsyncSession, storage: LocalStorage, user: User) -> dict[str, Any]:
    """Returns the ids the tests look for."""
    uid = user.id
    t = Base.metadata.tables
    ids = {name: uuid.uuid4() for name in (
        "year", "module", "topic", "subtopic", "exam", "quiz", "document", "question",
        "flashcard", "material", "version", "attempt", "answer", "exercise", "conversation",
        "message", "interaction", "plan", "draft",
    )}  # fmt: skip

    async def add(name: str, **row: Any) -> None:
        await db.execute(insert(t[name]).values(**row))

    await add(
        "academic_years",
        id=ids["year"],
        user_id=uid,
        label="2026/27",
        start_date=date(2026, 9, 21),
        end_date=date(2027, 6, 11),
        is_current=True,
    )
    await add(
        "modules",
        id=ids["module"],
        user_id=uid,
        academic_year_id=ids["year"],
        code="MATH101",
        title="Calculus I",
    )
    await add(
        "topics", id=ids["topic"], user_id=uid, module_id=ids["module"], title="Limits", position=0
    )
    # A child topic, listed first in id order half the time: restore must
    # still insert the parent first.
    await add(
        "topics",
        id=ids["subtopic"],
        user_id=uid,
        module_id=ids["module"],
        parent_id=ids["topic"],
        title="One-sided limits",
        position=0,
    )
    settings = t["user_settings"]  # made with the account
    await db.execute(update(settings).where(settings.c.user_id == uid).values(rest_weekdays=[5, 6]))
    await add("availability_rules", user_id=uid, weekday=0, minutes=90)
    await add("availability_overrides", user_id=uid, day=date(2026, 10, 10), minutes=0)
    await add("revision_plans", id=ids["plan"], user_id=uid, generated_at=NOW, params={"a": 1})
    await add(
        "exams",
        id=ids["exam"],
        user_id=uid,
        module_id=ids["module"],
        title="Final",
        starts_at=NOW + timedelta(days=60),
        duration_minutes=120,
    )
    await add("exam_topics", exam_id=ids["exam"], topic_id=ids["topic"], module_id=ids["module"])
    await add(
        "study_sessions",
        user_id=uid,
        module_id=ids["module"],
        topic_id=ids["topic"],
        exam_id=ids["exam"],
        plan_id=ids["plan"],
        kind="topic",
        day=date(2026, 10, 7),
        minutes=45,
        reason="Weakest topic",
    )
    await add(
        "notifications",
        user_id=uid,
        kind="exam",
        title="Final in 60 days",
        dedupe_key=f"exam:{ids['exam']}:60",
    )

    key = document_key(uid, ids["document"])
    await storage.put_bytes(key, PDF)
    await storage.put_bytes(page_image_key(uid, ids["document"], 1), PNG)
    await add(
        "documents",
        id=ids["document"],
        user_id=uid,
        module_id=ids["module"],
        topic_id=ids["topic"],
        original_filename="L1 limits.pdf",
        storage_key=key,
        mime="application/pdf",
        size_bytes=len(PDF),
        sha256=hashlib.sha256(PDF).digest(),
        source_tier="university",
        material_kind="lecture",
        status="ready",
        page_count=1,
    )
    await add(
        "document_pages",
        document_id=ids["document"],
        page_no=1,
        markdown="A limit $\\lim_{x\\to a} f(x)$.",
        extraction_method="text",
    )
    await add(
        "chunks",
        user_id=uid,
        document_id=ids["document"],
        module_id=ids["module"],
        topic_id=ids["topic"],
        source_tier="university",
        page_no=1,
        position=0,
        content="A limit.",
        token_estimate=3,
        embedding=[0.5] * DIM,
        embedding_model=MODEL,
    )

    await add(
        "ai_interactions",
        id=ids["interaction"],
        user_id=uid,
        feature="chat",
        requested_model="claude-haiku-4-5",
        prompt_version="chat.v1",
        status="ok",
        document_id=ids["document"],
    )
    await add(
        "ai_usage",
        user_id=uid,
        interaction_id=ids["interaction"],
        feature="chat",
        model="claude-haiku-4-5",
        input_tokens=100,
        output_tokens=50,
        estimated_cost_usd=0.001,
        module_id=ids["module"],
    )
    await add(
        "conversations",
        id=ids["conversation"],
        user_id=uid,
        title="Limits",
        module_id=ids["module"],
    )
    await add(
        "messages",
        id=ids["message"],
        conversation_id=ids["conversation"],
        user_id=uid,
        role="assistant",
        content=f"See [L1](/documents/{ids['document']}/pages/1).",
        citations=[{"document_id": str(ids["document"]), "page_no": 1}],
    )

    await add(
        "questions",
        id=ids["question"],
        user_id=uid,
        module_id=ids["module"],
        topic_id=ids["topic"],
        type="multiple_choice",
        difficulty="easy",
        rating=1500.0,
        stem_md="What is $\\lim_{x\\to0} x$?",
        answer_spec={"type": "multiple_choice", "options": ["0", "1"], "correct": 0},
        solution_md="It is 0.",
        origin="claude",
        embedding=[0.25] * DIM,
        sources=[{"document_id": str(ids["document"]), "page_no": 1}],
    )
    await add(
        "flashcards",
        id=ids["flashcard"],
        user_id=uid,
        module_id=ids["module"],
        topic_id=ids["topic"],
        front_md="Define a limit",
        back_md="$L$ such that ...",
        origin="user",
        embedding=[0.125] * DIM,
        due=NOW,
    )
    await add(
        "flashcard_reviews",
        user_id=uid,
        flashcard_id=ids["flashcard"],
        rating=3,
        reviewed_at=NOW,
        state_before=0,
        scheduled_days=1.0,
    )
    await add(
        "materials",
        id=ids["material"],
        user_id=uid,
        module_id=ids["module"],
        title="Limits summary",
        kind="summary",
        origin="claude",
        current_version_id=ids["version"],
    )
    await add(
        "material_versions",
        id=ids["version"],
        material_id=ids["material"],
        user_id=uid,
        version_no=1,
        content_md="Limits are ...",
        created_by="claude",
        ai_interaction_id=ids["interaction"],
    )
    await add(
        "drafts",
        id=ids["draft"],
        user_id=uid,
        module_id=ids["module"],
        kind="questions",
        request={"module_id": str(ids["module"])},
        status="saved",
    )
    await add(
        "quizzes",
        id=ids["quiz"],
        user_id=uid,
        module_id=ids["module"],
        kind="practice",
        title="Limits quiz",
    )
    await add(
        "quiz_items", quiz_id=ids["quiz"], position=0, user_id=uid, question_id=ids["question"]
    )
    await add(
        "quiz_attempts",
        id=ids["attempt"],
        user_id=uid,
        quiz_id=ids["quiz"],
        mode="normal",
        status="marked",
        score=1.0,
    )
    photo = answer_image_key(uid, ids["attempt"], ids["question"], "png")
    await storage.put_bytes(photo, PNG)
    await add(
        "question_attempts",
        id=ids["answer"],
        user_id=uid,
        quiz_attempt_id=ids["attempt"],
        question_id=ids["question"],
        response={"choice": 0},
        response_image_key=photo,
        score=1.0,
    )
    await add(
        "topic_mastery",
        user_id=uid,
        module_id=ids["module"],
        topic_id=ids["topic"],
        strength=0.7,
        accuracy=1.0,
        weight=1.0,
        attempts=1,
        ability=0.0,
        computed_at=NOW,
    )
    await add(
        "learning_profile_snapshots",
        user_id=uid,
        week_start=date(2026, 10, 5),
        metrics={"accuracy": 1.0},
        computed_at=NOW,
        ai_interaction_id=ids["interaction"],
    )
    await add(
        "coding_exercises",
        id=ids["exercise"],
        user_id=uid,
        module_id=ids["module"],
        language="python",
        title="Sum a list",
        prompt_md="Write `total(xs)`.",
        starter_code="def total(xs):\n    pass\n",
        solution_code="def total(xs):\n    return sum(xs)\n",
        tests=["assert total([1, 2]) == 3"],
        difficulty="easy",
        origin="user",
    )
    await add(
        "coding_submissions",
        user_id=uid,
        exercise_id=ids["exercise"],
        code="def total(xs):\n    return sum(xs)\n",
        results=[{"passed": True}],
        passed=1,
        total=1,
    )
    await add(
        "tutor_hints",
        user_id=uid,
        exercise_id=ids["exercise"],
        level=1,
        content_md="What does `sum` do?",
    )
    await db.commit()
    return ids
