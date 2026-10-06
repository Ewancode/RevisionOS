"""The parts of an export meant for people and other apps rather than for
restoring: CSV tables, Markdown notes and an Anki deck (SPEC 50).

Deleted items (in the trash) are left out here; the data folder has them.
"""

import csv
import hashlib
import io
import json
import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import genanki
import pypandoc
from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.practice.answers import (
    DerivationSpec,
    ExplanationSpec,
    ExpressionSpec,
    MultipleChoiceSpec,
    NumericalSpec,
    ShortAnswerSpec,
    TrueFalseSpec,
    load_spec,
)

RATINGS = {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}
# Fixed so that importing a newer export into Anki updates the same note type.
ANKI_MODEL_ID = 1_727_100_413
_UNSAFE = re.compile(r'[\x00-\x1f<>:"/\\|?*]+')


def _t(name: str) -> Table:
    return Base.metadata.tables[name]


def safe_name(text: str, limit: int = 80) -> str:
    """A file name that works on Windows, macOS and Linux."""
    cleaned = _UNSAFE.sub(" ", text).strip(" .") or "untitled"
    return re.sub(r"\s+", " ", cleaned)[:limit].rstrip(" .")


class Names:
    """Unique file names within one folder of the archive."""

    def __init__(self) -> None:
        self.used: set[str] = set()

    def __call__(self, folder: str, stem: str, suffix: str) -> str:
        base = f"{folder}/{safe_name(stem)}"
        name, n = f"{base}{suffix}", 2
        while name.lower() in self.used:
            name, n = f"{base} ({n}){suffix}", n + 1
        self.used.add(name.lower())
        return name


def answer_summary(spec_data: dict[str, Any]) -> str:
    """The expected answer, as a person would read it."""
    try:
        spec = load_spec(spec_data)
    except ValueError:
        return json.dumps(spec_data, ensure_ascii=False)
    if isinstance(spec, MultipleChoiceSpec):
        return spec.options[spec.correct] if 0 <= spec.correct < len(spec.options) else ""
    if isinstance(spec, TrueFalseSpec):
        return "True" if spec.answer else "False"
    if isinstance(spec, NumericalSpec):
        return f"{spec.value:g}" + (f" {spec.unit}" if spec.unit else "")
    if isinstance(spec, ExpressionSpec):
        return spec.answer
    if isinstance(spec, ShortAnswerSpec):
        return " / ".join(spec.accepted)
    if isinstance(spec, ExplanationSpec | DerivationSpec):
        return spec.model_answer
    return ""


def _csv(header: list[str], rows: Iterable[list[Any]]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    for row in rows:
        writer.writerow(["" if v is None else _cell(v) for v in row])
    # A byte-order mark so Excel opens UTF-8 (maths symbols) correctly.
    return ("﻿" + out.getvalue()).encode()


def _cell(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    return value


@dataclass
class Context:
    """Names for ids, loaded once."""

    modules: dict[uuid.UUID, tuple[str, str]] = field(default_factory=dict)  # code, title
    topics: dict[uuid.UUID, str] = field(default_factory=dict)

    def module(self, module_id: uuid.UUID | None) -> str:
        return self.modules[module_id][0] if module_id in self.modules else ""

    def topic(self, topic_id: uuid.UUID | None) -> str:
        return self.topics.get(topic_id, "") if topic_id else ""


async def load_context(db: AsyncSession, user_id: uuid.UUID) -> Context:
    modules, topics = _t("modules"), _t("topics")
    ctx = Context()
    for row in await db.execute(
        select(modules.c.id, modules.c.code, modules.c.title).where(modules.c.user_id == user_id)
    ):
        ctx.modules[row.id] = (row.code, row.title)
    for row in await db.execute(
        select(topics.c.id, topics.c.title).where(topics.c.user_id == user_id)
    ):
        ctx.topics[row.id] = row.title
    return ctx


Write = Callable[[str, bytes], None]


async def write_csvs(db: AsyncSession, user_id: uuid.UUID, ctx: Context, write: Write) -> None:
    q, fc = _t("questions"), _t("flashcards")
    rows = await db.execute(
        select(q).where(q.c.user_id == user_id, q.c.status == "active").order_by(q.c.created_at)
    )
    write("csv/questions.csv", _csv(
        ["id", "module", "topic", "type", "difficulty", "origin", "question", "answer",
         "solution", "created_at"],
        ([r.id, ctx.module(r.module_id), ctx.topic(r.topic_id), r.type, r.difficulty, r.origin,
          r.stem_md, answer_summary(r.answer_spec), r.solution_md, r.created_at] for r in rows),
    ))  # fmt: skip

    rows = await db.execute(
        select(fc)
        .where(fc.c.user_id == user_id, fc.c.deleted_at.is_(None))
        .order_by(fc.c.created_at)
    )
    write("csv/flashcards.csv", _csv(
        ["id", "module", "topic", "front", "back", "due", "reps", "lapses", "stability",
         "created_at"],
        ([r.id, ctx.module(r.module_id), ctx.topic(r.topic_id), r.front_md, r.back_md, r.due,
          r.reps, r.lapses, r.stability, r.created_at] for r in rows),
    ))  # fmt: skip

    qa = _t("question_attempts")
    rows = await db.execute(
        select(qa, q.c.module_id, q.c.topic_id, q.c.stem_md)
        .join(q, q.c.id == qa.c.question_id)
        .where(qa.c.user_id == user_id)
        .order_by(qa.c.created_at)
    )
    write("csv/answers.csv", _csv(
        ["answered_at", "module", "topic", "question", "your_answer", "score", "marked_by",
         "mistake", "seconds", "hints_used", "confidence"],
        ([r.created_at, ctx.module(r.module_id), ctx.topic(r.topic_id), r.stem_md, r.response,
          r.score, r.marked_by, r.mistake_category,
          None if r.time_ms is None else round(r.time_ms / 1000), r.hints_used,
          r.self_confidence] for r in rows),
    ))  # fmt: skip

    qz, at = _t("quizzes"), _t("quiz_attempts")
    rows = await db.execute(
        select(at, qz.c.module_id)
        .join(qz, qz.c.id == at.c.quiz_id)
        .where(at.c.user_id == user_id)
        .order_by(at.c.started_at)
    )
    write("csv/quizzes.csv", _csv(
        ["started_at", "module", "mode", "status", "submitted_at", "score"],
        ([r.started_at, ctx.module(r.module_id), r.mode, r.status, r.submitted_at, r.score]
         for r in rows),
    ))  # fmt: skip

    rv = _t("flashcard_reviews")
    rows = await db.execute(
        select(rv, fc.c.module_id, fc.c.front_md)
        .join(fc, fc.c.id == rv.c.flashcard_id)
        .where(rv.c.user_id == user_id)
        .order_by(rv.c.reviewed_at)
    )
    write("csv/flashcard_reviews.csv", _csv(
        ["reviewed_at", "module", "card", "rating", "seconds"],
        ([r.reviewed_at, ctx.module(r.module_id), r.front_md, RATINGS.get(r.rating, r.rating),
          None if r.duration_ms is None else round(r.duration_ms / 1000)] for r in rows),
    ))  # fmt: skip

    ss = _t("study_sessions")
    rows = await db.execute(
        select(ss).where(ss.c.user_id == user_id).order_by(ss.c.day, ss.c.created_at)
    )
    write("csv/study_sessions.csv", _csv(
        ["day", "module", "topic", "kind", "minutes", "status", "actual_minutes",
         "completed_at", "reason"],
        ([r.day, ctx.module(r.module_id), ctx.topic(r.topic_id), r.kind, r.minutes, r.status,
          r.actual_minutes, r.completed_at, r.reason] for r in rows),
    ))  # fmt: skip

    ex = _t("exams")
    rows = await db.execute(select(ex).where(ex.c.user_id == user_id).order_by(ex.c.starts_at))
    write("csv/exams.csv", _csv(
        ["module", "title", "starts_at", "duration_minutes", "location", "weighting",
         "confidence", "notes"],
        ([ctx.module(r.module_id), r.title, r.starts_at, r.duration_minutes, r.location,
          r.weighting, r.confidence, r.notes] for r in rows),
    ))  # fmt: skip

    tm = _t("topic_mastery")
    rows = await db.execute(select(tm).where(tm.c.user_id == user_id))
    write("csv/topic_progress.csv", _csv(
        ["module", "topic", "strength", "accuracy", "retrievability", "attempts",
         "last_practised_at"],
        ([ctx.module(r.module_id), ctx.topic(r.topic_id), r.strength, r.accuracy,
          r.retrievability, r.attempts, r.last_practised_at] for r in rows),
    ))  # fmt: skip

    ce, cs = _t("coding_exercises"), _t("coding_submissions")
    rows = await db.execute(
        select(cs, ce.c.module_id, ce.c.title, ce.c.language)
        .join(ce, ce.c.id == cs.c.exercise_id)
        .where(cs.c.user_id == user_id)
        .order_by(cs.c.created_at)
    )
    write("csv/coding_submissions.csv", _csv(
        ["submitted_at", "module", "exercise", "language", "tests_passed", "tests", "error",
         "runtime_ms"],
        ([r.created_at, ctx.module(r.module_id), r.title, r.language, r.passed, r.total,
          r.error, r.runtime_ms] for r in rows),
    ))  # fmt: skip


def _module_folder(ctx: Context, module_id: uuid.UUID) -> str:
    code, title = ctx.modules.get(module_id, ("", "Unknown module"))
    return "markdown/" + safe_name(f"{code} {title}".strip())


async def write_markdown(db: AsyncSession, user_id: uuid.UUID, ctx: Context, write: Write) -> None:
    names = Names()

    # Revision materials: each one's current version.
    m, mv = _t("materials"), _t("material_versions")
    rows = await db.execute(
        select(m.c.module_id, m.c.title, m.c.kind, mv.c.content_md, mv.c.version_no)
        .join(mv, mv.c.id == m.c.current_version_id)
        .where(m.c.user_id == user_id, m.c.deleted_at.is_(None))
        .order_by(m.c.title)
    )
    for r in rows:
        name = names(_module_folder(ctx, r.module_id) + "/materials", r.title, ".md")
        write(name, f"# {r.title}\n\n{r.content_md}\n".encode())

    # Lecture materials as extracted text, page by page.
    d, p = _t("documents"), _t("document_pages")
    docs = (
        await db.execute(
            select(d.c.id, d.c.module_id, d.c.original_filename)
            .where(d.c.user_id == user_id, d.c.deleted_at.is_(None))
            .order_by(d.c.original_filename)
        )
    ).all()
    for doc in docs:
        pages = await db.execute(
            select(p.c.page_no, p.c.markdown).where(p.c.document_id == doc.id).order_by(p.c.page_no)
        )
        body = "\n\n".join(f"## Page {pg.page_no}\n\n{pg.markdown}" for pg in pages)
        name = names(_module_folder(ctx, doc.module_id) + "/lectures", doc.original_filename, ".md")
        write(name, f"# {doc.original_filename}\n\n{body}\n".encode())

    # The question bank and flashcards, one file per module.
    q = _t("questions")
    by_module: dict[uuid.UUID, list[str]] = {}
    for r in await db.execute(
        select(q).where(q.c.user_id == user_id, q.c.status == "active").order_by(q.c.created_at)
    ):
        options = (r.answer_spec or {}).get("options") if r.type == "multiple_choice" else None
        choices = "".join(f"\n- {o}" for o in options) if options else ""
        topic = f" · {ctx.topic(r.topic_id)}" if r.topic_id else ""
        by_module.setdefault(r.module_id, []).append(
            f"## {r.type.replace('_', ' ').capitalize()} ({r.difficulty}){topic}\n\n"
            f"{r.stem_md}{choices}\n\n**Answer:** {answer_summary(r.answer_spec)}\n\n"
            f"{r.solution_md or ''}".rstrip()
        )
    for module_id, items in by_module.items():
        write(_module_folder(ctx, module_id) + "/questions.md",
              ("# Questions\n\n" + "\n\n---\n\n".join(items) + "\n").encode())  # fmt: skip

    fc = _t("flashcards")
    by_module = {}
    for r in await db.execute(
        select(fc.c.module_id, fc.c.front_md, fc.c.back_md)
        .where(fc.c.user_id == user_id, fc.c.deleted_at.is_(None))
        .order_by(fc.c.created_at)
    ):
        by_module.setdefault(r.module_id, []).append(f"**Q:** {r.front_md}\n\n**A:** {r.back_md}")
    for module_id, items in by_module.items():
        write(_module_folder(ctx, module_id) + "/flashcards.md",
              ("# Flashcards\n\n" + "\n\n---\n\n".join(items) + "\n").encode())  # fmt: skip

    # Coding exercises.
    ce = _t("coding_exercises")
    for r in await db.execute(
        select(ce).where(ce.c.user_id == user_id, ce.c.deleted_at.is_(None)).order_by(ce.c.title)
    ):
        fence = "python" if r.language == "python" else "r"
        text = (
            f"# {r.title}\n\n{r.prompt_md}\n\n## Starter code\n\n```{fence}\n{r.starter_code}\n```"
            f"\n\n## Reference solution\n\n```{fence}\n{r.solution_code}\n```\n"
        )
        write(names(_module_folder(ctx, r.module_id) + "/coding", r.title, ".md"), text.encode())

    # Conversations with the assistant.
    cv, msg = _t("conversations"), _t("messages")
    conversations = (
        await db.execute(
            select(cv.c.id, cv.c.title, cv.c.created_at)
            .where(cv.c.user_id == user_id)
            .order_by(cv.c.created_at)
        )
    ).all()
    for conv in conversations:
        messages = await db.execute(
            select(msg.c.role, msg.c.content, msg.c.created_at)
            .where(msg.c.conversation_id == conv.id)
            .order_by(msg.c.created_at)
        )
        turns = "\n\n".join(
            f"**{'You' if m_.role == 'user' else 'Assistant'}** ({m_.created_at:%Y-%m-%d %H:%M}):"
            f"\n\n{m_.content}"
            for m_ in messages
        )
        title = conv.title or "Conversation"
        name = names("markdown/conversations", f"{conv.created_at:%Y-%m-%d} {title}", ".md")
        write(name, f"# {title}\n\n{turns}\n".encode())


def to_html(markdown_texts: list[str]) -> list[str]:
    """Card fields as HTML with MathJax maths (Anki shows \\(..\\) and \\[..\\]),
    converted in one pandoc run: one process per card would take minutes."""
    if not markdown_texts:
        return []
    doc = "\n\n".join(f"::: {{#f{i}}}\n{text}\n:::" for i, text in enumerate(markdown_texts))
    html = pypandoc.convert_text(doc, "html", format="markdown", extra_args=["--mathjax"])
    parts = re.split(r'<div id="f(\d+)">', html)
    found: dict[int, str] = {}
    for index, body in zip(parts[1::2], parts[2::2], strict=True):
        found[int(index)] = re.sub(r"</div>\s*$", "", body.strip()).strip()
    # Anything pandoc could not keep apart (an odd ":::" in a card) is shown
    # as escaped text rather than lost.
    return [found.get(i, _escape(text)) for i, text in enumerate(markdown_texts)]


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    )


def _stable_id(text: str) -> int:
    """Anki deck ids: stable per module, in Anki's id range."""
    return int(hashlib.sha256(text.encode()).hexdigest()[:12], 16) % (1 << 31) + (1 << 30)


async def anki_package(db: AsyncSession, user_id: uuid.UUID, ctx: Context, path: Path) -> int:
    """Every flashcard as an Anki deck per module ("Revision OS::MATH101 ...").
    Each note's id comes from the card's id, so importing a later export
    updates notes instead of duplicating them. Returns the number of cards."""
    fc = _t("flashcards")
    cards = (
        await db.execute(
            select(fc.c.id, fc.c.module_id, fc.c.topic_id, fc.c.front_md, fc.c.back_md)
            .where(fc.c.user_id == user_id, fc.c.deleted_at.is_(None))
            .order_by(fc.c.created_at)
        )
    ).all()
    if not cards:
        return 0
    html = to_html([t for c in cards for t in (c.front_md, c.back_md)])
    model = genanki.Model(
        ANKI_MODEL_ID,
        "Revision OS card",
        fields=[{"name": "Front"}, {"name": "Back"}],
        templates=[
            {
                "name": "Card 1",
                "qfmt": "{{Front}}",
                "afmt": '{{FrontSide}}<hr id="answer">{{Back}}',
            }
        ],
    )
    decks: dict[uuid.UUID, genanki.Deck] = {}
    for i, card in enumerate(cards):
        code, title = ctx.modules.get(card.module_id, ("", "Unknown module"))
        name = f"Revision OS::{code} {title}".strip()
        deck = decks.setdefault(card.module_id, genanki.Deck(_stable_id(str(card.module_id)), name))
        tags = [re.sub(r"\s+", "_", ctx.topic(card.topic_id))] if card.topic_id else []
        deck.add_note(
            genanki.Note(
                model=model,
                fields=[html[2 * i], html[2 * i + 1]],
                guid=genanki.guid_for(str(card.id)),
                tags=[t for t in tags if t],
            )
        )
    genanki.Package(list(decks.values())).write_to_file(str(path))
    return len(cards)
