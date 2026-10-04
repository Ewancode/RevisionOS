"""Generating materials, questions and flashcards as drafts (ARCHITECTURE.md
sections 7-9; SPEC 18, 26, 29 and 40).

Runs in the worker. Every draft is written from passages of the student's own
materials: the pages of files they chose, or the best search results for the
topic. Nothing is saved until the student chooses to save the draft.

- Materials are Markdown with verified citations (as in assistant answers).
- Questions and flashcards come back as structured JSON. Each item is
  checked (app.practice.validation) and against the bank for near-duplicates.
  Items that fail get one repair attempt on the route's stronger model; any
  still failing are shown in the preview with their problems and cannot be
  saved.
"""

import json
import logging
import math
import random
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chat import Answer
from app.ai.client import ClaudeClient, parse_json, text_tokens
from app.ai.tools import Source, passage_header, search_result
from app.coding.validation import CODING_SCHEMA, check_exercise
from app.core.config import AppConfig
from app.core.errors import AppError
from app.models import (
    Chunk,
    Document,
    DocumentPage,
    Draft,
    Flashcard,
    Material,
    MaterialVersion,
    Module,
    Question,
    Topic,
)
from app.practice.validation import (
    FLASHCARD_SCHEMA,
    QUESTION_SCHEMA,
    check_flashcard,
    check_question,
)
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.search import Passage, Scope, SearchService

logger = logging.getLogger(__name__)

PROMPTS = Path(__file__).parent.parent / "ai" / "prompts"
MATERIAL_PROMPT = "generate_material.v1"
QUESTIONS_PROMPT = "generate_questions.v2"
FLASHCARDS_PROMPT = "generate_flashcards.v1"
CODING_PROMPT = "generate_coding.v1"
TITLE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
KIND_NAMES = {
    "guide": "revision guide",
    "summary": "topic summary",
    "formula_sheet": "formula sheet",
    "worked_examples": "set of worked examples",
    "definitions": "list of key definitions",
    "explanation": "topic explanation",
    "concept_map": "concept map (as a nested Markdown outline of concepts and how they relate)",
    "notes": "set of revision notes",
}


@lru_cache
def prompt(version: str) -> str:
    return (PROMPTS / f"{version}.md").read_text(encoding="utf-8")


@dataclass
class Context:
    module: Module
    topic: Topic | None
    passages: list[Passage]


# --- gathering what to write from -----------------------------------------------------


async def _file_passages(
    db: AsyncSession, user_id: uuid.UUID, module: Module, ids: Sequence[str], limit: int
) -> list[Passage]:
    """Pages of the chosen files, in order, up to `limit` characters."""
    rows = (
        await db.execute(
            select(DocumentPage, Document)
            .join(Document, Document.id == DocumentPage.document_id)
            .where(
                Document.id.in_([uuid.UUID(i) for i in ids]),
                Document.user_id == user_id,
                Document.deleted_at.is_(None),
            )
            .order_by(Document.created_at, DocumentPage.page_no)
        )
    ).all()
    passages, used = [], 0
    for page, doc in rows:
        text = page.markdown.strip()
        if not text:
            continue
        if used + len(text) > limit:
            break
        used += len(text)
        passages.append(
            Passage(
                chunk_id=uuid.uuid4(),
                document_id=doc.id,
                filename=doc.original_filename,
                module_id=doc.module_id,
                module_code=module.code,
                page_no=page.page_no,
                heading_path="",
                content=text,
                source_tier=doc.source_tier,
                score=0.0,
                matched="both",
            )
        )
    return passages


async def gather(
    db: AsyncSession, embedder: EmbeddingProvider, config: AppConfig, draft: Draft
) -> Context:
    module = await db.get(Module, draft.module_id)
    if module is None:
        raise AppError("module_not_found", "That module does not exist.", 404)
    topic = await db.get(Topic, draft.topic_id) if draft.topic_id else None
    request = draft.request
    generation = config.practice.generation
    if request.get("document_ids"):
        passages = await _file_passages(
            db, draft.user_id, module, request["document_ids"], generation.max_context_chars
        )
    else:
        focus = " ".join(
            p for p in (topic.title if topic else None, request.get("instructions")) if p
        )
        passages = []
        if focus:
            search_config = config.retrieval.search.model_copy(
                update={"results": generation.passages}
            )
            service = SearchService(db, draft.user_id, embedder, search_config)
            scope = Scope(module.academic_year_id, module.id, topic.id if topic else None)
            passages = (await service.search(focus, scope)).passages
        # No focus ("questions on this module"), or search found little: draw
        # passages from across the module so the whole course is covered.
        if len(passages) < generation.passages // 2:
            seen = {(p.document_id, p.page_no) for p in passages}
            extra = await _spread_passages(db, draft.user_id, module, generation.passages)
            passages += [p for p in extra if (p.document_id, p.page_no) not in seen]
            passages = passages[: generation.passages]
    return Context(module, topic, passages)


async def _spread_passages(
    db: AsyncSession, user_id: uuid.UUID, module: Module, count: int
) -> list[Passage]:
    """A random sample of the module's chunks, one per page, university
    material first. Random, so repeated requests cover different pages."""
    rows = (
        await db.execute(
            select(Chunk, Document.original_filename)
            .join(Document, Document.id == Chunk.document_id)
            .where(
                Chunk.user_id == user_id,
                Chunk.module_id == module.id,
                Document.deleted_at.is_(None),
            )
        )
    ).all()
    by_page: dict[tuple[uuid.UUID, int], tuple[Chunk, str]] = {}
    for chunk, filename in rows:
        by_page.setdefault((chunk.document_id, chunk.page_no), (chunk, filename))
    pages = list(by_page.values())
    rng = random.Random()  # noqa: S311 - choosing pages, not security
    rng.shuffle(pages)
    pages.sort(key=lambda row: row[0].source_tier != "university")
    return [
        Passage(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            filename=filename,
            module_id=module.id,
            module_code=module.code,
            page_no=chunk.page_no,
            heading_path=chunk.heading_path,
            content=chunk.content,
            source_tier=chunk.source_tier,
            score=0.0,
            matched="both",
        )
        for chunk, filename in pages[:count]
    ]


def _where(context: Context) -> str:
    where = f"{context.module.code} {context.module.title}"
    return f"the topic “{context.topic.title}” in {where}" if context.topic else where


def _numbered(passages: Sequence[Passage]) -> str:
    return "\n\n".join(
        f"[P{i}] {p.filename} — page {p.page_no} {passage_header(p)}\n{p.content}"
        for i, p in enumerate(passages, 1)
    )


def _source_refs(passages: Sequence[Passage]) -> list[dict[str, Any]]:
    return [
        {
            "n": i,
            "document_id": str(p.document_id),
            "filename": p.filename,
            "page_no": p.page_no,
            "source_tier": p.source_tier,
        }
        for i, p in enumerate(passages, 1)
    ]


def no_material() -> AppError:
    return AppError(
        "no_material",
        "None of your materials for this module or topic matched. Upload some, or choose files.",
        422,
    )


# --- materials -----------------------------------------------------------------------------


async def generate_material(
    db: AsyncSession, claude: ClaudeClient, config: AppConfig, draft: Draft, context: Context
) -> tuple[dict[str, Any], uuid.UUID]:
    request = draft.request
    if not context.passages:
        raise no_material()
    sources: list[Source] = []
    blocks = []
    for passage in context.passages:
        source, block = search_result(passage)
        sources.append(source)
        blocks.append(block)
    kind = KIND_NAMES.get(request.get("material_kind") or "guide", "revision guide")
    lines = [f"Write a {kind} for {_where(context)}."]
    if request.get("instructions"):
        lines.append(f"The student asks: {request['instructions']}")
    if request.get("improve_material_id"):
        base = await _current_text(db, draft.user_id, uuid.UUID(request["improve_material_id"]))
        lines.append(
            "Improve the student's existing material below. Their original is kept; you are "
            f"writing a new version.\n<existing_material>\n{base}\n</existing_material>"
        )
    instruction = "\n\n".join(lines)
    system = prompt(MATERIAL_PROMPT)
    result = await claude.run(
        db,
        user_id=draft.user_id,
        task="revision_guide",
        prompt_version=MATERIAL_PROMPT,
        system=system,
        content=[*blocks, {"type": "text", "text": instruction}],
        estimated_input_tokens=text_tokens(system)
        + text_tokens(instruction)
        + text_tokens(json.dumps(blocks)),
        module_id=context.module.id,
    )
    answer = Answer(config.ai.chat.cited_text_max_chars)
    for block in result.content:
        if getattr(block, "type", None) == "text":
            answer.add_text_block(block, sources)
    content = answer.content
    match = TITLE.search(content)
    title = match.group(1).strip() if match else f"{context.module.code} {kind}"
    return {
        "title": title[:200],
        "content_md": content,
        "citations": answer.citations,
    }, result.interaction_id


async def _current_text(db: AsyncSession, user_id: uuid.UUID, material_id: uuid.UUID) -> str:
    row = (
        await db.execute(
            select(MaterialVersion.content_md)
            .join(Material, Material.current_version_id == MaterialVersion.id)
            .where(
                Material.id == material_id,
                Material.user_id == user_id,
                Material.deleted_at.is_(None),
            )
        )
    ).first()
    if row is None:
        raise AppError("material_not_found", "That material does not exist.", 404)
    return str(row[0])


# --- near-duplicates ---------------------------------------------------------------------


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


async def near_duplicates(
    db: AsyncSession,
    embedder: EmbeddingProvider,
    model: type[Question] | type[Flashcard],
    user_id: uuid.UUID,
    module_id: uuid.UUID,
    texts: list[str],
    threshold: float,
) -> tuple[list[str | None], list[list[float]]]:
    """For each text, why it is a near-duplicate (or None), and its embedding."""
    vectors = await embedder.embed_passages(texts)
    live = Question.status == "active" if model is Question else Flashcard.deleted_at.is_(None)
    reasons: list[str | None] = []
    for i, vector in enumerate(vectors):
        distance = await db.scalar(
            select(func.min(model.embedding.cosine_distance(vector))).where(
                model.user_id == user_id,
                model.module_id == module_id,
                model.embedding.is_not(None),
                live,
            )
        )
        kind = "question" if model is Question else "card"
        if distance is not None and 1 - float(distance) >= threshold:
            reasons.append(f"almost the same as a {kind} already saved")
        elif any(_cosine(vector, vectors[j]) >= threshold for j in range(i)):
            reasons.append(f"almost the same as another {kind} in this draft")
        else:
            reasons.append(None)
    return reasons, vectors


# --- questions and flashcards ------------------------------------------------------------


def _question_route(request: dict[str, Any]) -> str:
    hard = request.get("difficulty") in ("hard", "exam")
    written = bool({"explanation", "derivation"} & set(request.get("types") or []))
    return "exam_question_generation" if hard or written else "simple_question_generation"


def _items_request(kind: str, count: int, request: dict[str, Any], context: Context) -> str:
    lines = [f"Write {count} {kind} for {_where(context)}."]
    if kind == "questions":
        difficulty = request.get("difficulty") or "mixed"
        lines.append(
            "Difficulty: a mix of easy, medium and hard."
            if difficulty == "mixed"
            else f"Difficulty: {difficulty}."
        )
        types = request.get("types")
        lines.append(
            f"Types allowed: {', '.join(types)}." if types else "Choose the best type for each."
        )
    if request.get("instructions"):
        lines.append(f"The student asks: {request['instructions']}")
    lines.append(f"Passages:\n\n{_numbered(context.passages)}")
    return "\n\n".join(lines)


async def _ask_json(
    db: AsyncSession,
    claude: ClaudeClient,
    draft: Draft,
    context: Context,
    *,
    task: str,
    version: str,
    text: str,
    schema: dict[str, Any],
    escalate: bool = False,
) -> tuple[list[dict[str, Any]], uuid.UUID]:
    system = prompt(version)
    result = await claude.run(
        db,
        user_id=draft.user_id,
        task=task,
        prompt_version=version,
        system=system,
        content=[{"type": "text", "text": text}],
        estimated_input_tokens=text_tokens(system) + text_tokens(text),
        output_schema=schema,
        escalate=escalate,
        module_id=context.module.id,
    )
    items = parse_json(result.text).get("items")
    if not isinstance(items, list):
        raise AppError("ai_bad_output", "Claude returned malformed output.", 502)
    return [i for i in items if isinstance(i, dict)], result.interaction_id


async def generate_items(
    db: AsyncSession,
    claude: ClaudeClient,
    embedder: EmbeddingProvider,
    config: AppConfig,
    draft: Draft,
    context: Context,
) -> tuple[dict[str, Any], uuid.UUID]:
    """Questions or flashcards, checked; failures repaired once."""
    if not context.passages:
        raise no_material()
    generation, practice = config.practice.generation, config.practice
    questions = draft.kind == "questions"
    count = min(draft.request.get("count") or generation.default_items, generation.max_items)
    task = _question_route(draft.request) if questions else "flashcard_generation"
    version = QUESTIONS_PROMPT if questions else FLASHCARDS_PROMPT
    schema = QUESTION_SCHEMA if questions else FLASHCARD_SCHEMA
    n = len(context.passages)

    def check(raw: dict[str, Any]) -> list[str]:
        if questions:
            return check_question(raw, n, practice.validation, practice.marking).problems
        return check_flashcard(raw, n, practice.validation).problems

    request_text = _items_request(
        "questions" if questions else "flashcards", count, draft.request, context
    )
    raw_items, interaction = await _ask_json(
        db, claude, draft, context, task=task, version=version, text=request_text, schema=schema
    )
    items = [{**raw, "problems": check(raw)} for raw in raw_items[:count]]

    for _ in range(generation.repair_rounds):
        broken = [i for i, item in enumerate(items) if item["problems"]]
        if not broken:
            break
        repair_text = (
            f"{request_text}\n\nThese items failed the app's checks. Return corrected versions "
            "of exactly these items, in this order:\n\n"
            + json.dumps(
                [
                    {
                        "item": {k: v for k, v in items[i].items() if k != "problems"},
                        "problems": items[i]["problems"],
                    }
                    for i in broken
                ],
                ensure_ascii=False,
            )
        )
        try:
            repaired, _ = await _ask_json(
                db, claude, draft, context,
                task=task, version=version, text=repair_text, schema=schema, escalate=True,
            )  # fmt: skip
        except AppError as exc:
            logger.warning("repair failed", extra={"error": exc.code})
            break
        for i, raw in zip(broken, repaired, strict=False):
            problems = check(raw)
            if not problems or len(problems) < len(items[i]["problems"]):
                items[i] = {**raw, "problems": problems, "repaired": True}

    texts = [str(item.get("stem_md" if questions else "front_md") or "") for item in items]
    reasons, vectors = await near_duplicates(
        db,
        embedder,
        Question if questions else Flashcard,
        draft.user_id,
        draft.module_id,
        texts,
        generation.near_duplicate_similarity,
    )
    for item, reason, vector in zip(items, reasons, vectors, strict=True):
        if reason:
            item["problems"].append(reason)
        item["valid"] = not item["problems"]
        item["embedding"] = vector
    return {"items": items, "passages": _source_refs(context.passages)}, interaction


async def generate_coding(
    db: AsyncSession,
    claude: ClaudeClient,
    config: AppConfig,
    draft: Draft,
    context: Context,
) -> tuple[dict[str, Any], uuid.UUID]:
    """Coding exercises, checked (statically: the server never runs code);
    failures repaired once. Passages ground them when the module has any,
    but are not required: a coding exercise can stand on its own."""
    coding = config.coding
    count = min(
        draft.request.get("count") or coding.generation.default_items, coding.generation.max_items
    )
    language = draft.request.get("language") or "python"
    language_name = "Python" if language == "python" else "R"
    n = len(context.passages)

    def check(raw: dict[str, Any]) -> list[str]:
        problems = check_exercise(raw, n, coding.limits).problems
        if raw.get("language") != language:
            problems.append(f"It should be in {language_name}.")
        return problems

    lines = [
        f"Write {count} coding exercise{'s' if count != 1 else ''} in {language_name} "
        f"for {_where(context)}."
    ]
    difficulty = draft.request.get("difficulty")
    if difficulty and difficulty != "mixed":
        lines.append(f"Difficulty: {difficulty}.")
    if draft.request.get("instructions"):
        lines.append(f"The student asks: {draft.request['instructions']}")
    lines.append(
        f"Passages:\n\n{_numbered(context.passages)}"
        if context.passages
        else "There are no passages: base the exercises on the module's subject."
    )
    request_text = "\n\n".join(lines)
    raw_items, interaction = await _ask_json(
        db, claude, draft, context,
        task="coding_generation", version=CODING_PROMPT, text=request_text, schema=CODING_SCHEMA,
    )  # fmt: skip
    items = [{**raw, "problems": check(raw)} for raw in raw_items[:count]]
    for _ in range(config.practice.generation.repair_rounds):
        broken = [i for i, item in enumerate(items) if item["problems"]]
        if not broken:
            break
        repair_text = (
            f"{request_text}\n\nThese exercises failed the app's checks. Return corrected "
            "versions of exactly these, in this order:\n\n"
            + json.dumps(
                [
                    {
                        "item": {k: v for k, v in items[i].items() if k != "problems"},
                        "problems": items[i]["problems"],
                    }
                    for i in broken
                ],
                ensure_ascii=False,
            )
        )
        try:
            repaired, _ = await _ask_json(
                db, claude, draft, context,
                task="coding_generation", version=CODING_PROMPT, text=repair_text,
                schema=CODING_SCHEMA, escalate=True,
            )  # fmt: skip
        except AppError as exc:
            logger.warning("repair failed", extra={"error": exc.code})
            break
        for i, raw in zip(broken, repaired, strict=False):
            problems = check(raw)
            if not problems or len(problems) < len(items[i]["problems"]):
                items[i] = {**raw, "problems": problems, "repaired": True}
    for item in items:
        item["valid"] = not item["problems"]
    return {"items": items, "passages": _source_refs(context.passages)}, interaction


# --- the worker job -----------------------------------------------------------------------


async def run_draft(
    db: AsyncSession,
    claude: ClaudeClient,
    embedder: EmbeddingProvider,
    config: AppConfig,
    draft_id: uuid.UUID,
) -> None:
    draft = await db.get(Draft, draft_id)
    if draft is None or draft.status != "generating":
        return
    try:
        context = await gather(db, embedder, config, draft)
        if draft.kind == "material":
            payload, interaction = await generate_material(db, claude, config, draft, context)
        elif draft.kind == "coding":
            payload, interaction = await generate_coding(db, claude, config, draft, context)
        else:
            payload, interaction = await generate_items(
                db, claude, embedder, config, draft, context
            )
    except Exception as exc:
        # Whatever went wrong, the draft must not stay "generating" forever.
        code = exc.code if isinstance(exc, AppError) else "internal_error"
        if not isinstance(exc, AppError):
            logger.exception("draft generation failed", extra={"draft_id": str(draft_id)})
        await db.rollback()
        draft = await db.get(Draft, draft_id)
        if draft is not None:
            draft.status, draft.error_code = "failed", code
            await db.commit()
        return
    draft.payload, draft.ai_interaction_id = payload, interaction
    draft.status, draft.error_code = "ready", None
    await db.commit()
    if draft.request.get("auto") and draft.kind == "questions":
        await _auto_save(db, config, draft)


async def _auto_save(db: AsyncSession, config: AppConfig, draft: Draft) -> None:
    """Save the valid questions of a daily-quiz top-up straight to the bank."""
    # Imported here: the drafts service imports this module.
    from app.schemas.practice import DraftSave
    from app.services.common import ClientInfo
    from app.services.drafts import DraftService

    if not any(item.get("valid") for item in (draft.payload or {}).get("items", [])):
        return
    service = DraftService(
        db, draft.user_id, ClientInfo(None, "worker"), config=config, jobs=_NoJobs()
    )
    await service.save(draft.id, DraftSave())


class _NoJobs:
    async def enqueue(self, function: str, *args: object, job_id: str | None = None) -> None:
        raise RuntimeError("saving a draft queues no jobs")
