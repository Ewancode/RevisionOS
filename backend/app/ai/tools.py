"""The assistant's tools (ARCHITECTURE.md section 9).

Each tool is a Pydantic input model, a handler that goes through the same
user-scoped services and queries as the UI, and a risk level. Read tools run
automatically. Destructive tools never delete: they create a pending action
that only the user can confirm.

Passages returned to Claude are `search_result` blocks, which let Claude cite
them. Each block supplied in a turn is registered in `ToolContext.sources`, in
the order Claude sees them, so the server can check every citation it gets
back against what it actually sent.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig
from app.core.errors import AppError
from app.models import AcademicYear, Document, DocumentPage, Module, PendingAction, Topic
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.search import Passage, Scope, SearchService
from app.services.common import ClientInfo
from app.services.pending_actions import PendingActionService
from app.workers.queue import JobQueue

logger = logging.getLogger(__name__)

Risk = Literal["read", "draft", "destructive"]


@dataclass(frozen=True)
class Source:
    """One passage Claude was shown, identified by `source` in citations."""

    source: str
    title: str
    document_id: uuid.UUID
    filename: str
    page_no: int
    source_tier: str
    module_code: str
    heading_path: str


def source_id(document_id: uuid.UUID, page_no: int) -> str:
    return f"doc:{document_id}#page={page_no}"


def source_title(filename: str, page_no: int) -> str:
    return f"{filename} — page {page_no}"


@dataclass
class ToolContext:
    db: AsyncSession
    user_id: uuid.UUID
    client: ClientInfo
    embedder: EmbeddingProvider
    config: AppConfig
    scope: Scope
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    jobs: JobQueue | None = None
    sources: list[Source] = field(default_factory=list)
    actions: list[PendingAction] = field(default_factory=list)
    # Things made on the way, e.g. drafts: [{"kind": "draft", "id", "label"}].
    links: list[dict[str, Any]] = field(default_factory=list)

    def add_source(self, passage: Passage) -> dict[str, Any]:
        """Register a passage and return it as a citable search_result block."""
        source, block = search_result(passage)
        self.sources.append(source)
        return block


def passage_header(passage: Passage) -> str:
    tier = "university material" if passage.source_tier == "university" else "student's own notes"
    header = f"[{passage.module_code} · {tier}"
    return header + (f" · {passage.heading_path}]" if passage.heading_path else "]")


def search_result(passage: Passage) -> tuple[Source, dict[str, Any]]:
    """A passage as a citable `search_result` block, and the record used to
    check citations to it."""
    source = Source(
        source=source_id(passage.document_id, passage.page_no),
        title=source_title(passage.filename, passage.page_no),
        document_id=passage.document_id,
        filename=passage.filename,
        page_no=passage.page_no,
        source_tier=passage.source_tier,
        module_code=passage.module_code,
        heading_path=passage.heading_path,
    )
    block = {
        "type": "search_result",
        "source": source.source,
        "title": source.title,
        "content": [{"type": "text", "text": f"{passage_header(passage)}\n{passage.content}"}],
        "citations": {"enabled": True},
    }
    return source, block


@dataclass(frozen=True)
class ToolOutput:
    # A plain string, or a list of search_result blocks.
    content: str | list[dict[str, Any]]
    is_error: bool = False


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Handler = Callable[[ToolContext, Any], Awaitable[ToolOutput]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    risk: Risk
    input_model: type[_Input]
    handler: Handler
    # Status line shown to the user while the tool runs.
    status: Callable[[Any], str]

    def definition(self) -> dict[str, Any]:
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        return {"name": self.name, "description": self.description, "input_schema": schema}


# --- read tools -----------------------------------------------------------------


class SearchInput(_Input):
    query: str = Field(min_length=1, max_length=300, description="What to look for.")
    module_code: str | None = Field(
        default=None,
        max_length=20,
        description="Limit the search to one module, e.g. MATH101. Omit to search from where "
        "the student is asking (it widens automatically if little is found).",
    )


async def _module_by_code(ctx: ToolContext, code: str) -> Module | None:
    return await ctx.db.scalar(
        select(Module).where(
            Module.user_id == ctx.user_id,
            Module.deleted_at.is_(None),
            func.upper(Module.code) == code.strip().upper(),
        )
    )


async def search_materials(ctx: ToolContext, args: SearchInput) -> ToolOutput:
    scope = ctx.scope
    if args.module_code:
        module = await _module_by_code(ctx, args.module_code)
        if module is None:
            return ToolOutput(
                f"No module with code {args.module_code}. Use list_materials to see them.", True
            )
        scope = Scope(module.academic_year_id, module.id)
    service = SearchService(ctx.db, ctx.user_id, ctx.embedder, ctx.config.retrieval.search)
    result = await service.search(args.query, scope)
    if not result.passages:
        return ToolOutput("No passages in the student's materials matched this search.")
    return ToolOutput([ctx.add_source(p) for p in result.passages])


class ReadPageInput(_Input):
    document_id: uuid.UUID = Field(description="The file's id, from a passage or list_materials.")
    page_no: int = Field(ge=1, description="Page number, as in the passage title.")


async def read_page(ctx: ToolContext, args: ReadPageInput) -> ToolOutput:
    row = (
        await ctx.db.execute(
            select(DocumentPage, Document, Module.code)
            .join(Document, Document.id == DocumentPage.document_id)
            .join(Module, Module.id == Document.module_id)
            .where(
                DocumentPage.document_id == args.document_id,
                DocumentPage.page_no == args.page_no,
                Document.user_id == ctx.user_id,
                Document.deleted_at.is_(None),
            )
        )
    ).first()
    if row is None:
        return ToolOutput("That page does not exist.", True)
    page, doc, code = row
    limit = ctx.config.ai.chat.page_read_max_chars
    text = page.markdown if len(page.markdown) <= limit else page.markdown[:limit] + "\n[…page cut]"
    passage = Passage(
        chunk_id=uuid.uuid4(),
        document_id=doc.id,
        filename=doc.original_filename,
        module_id=doc.module_id,
        module_code=code,
        page_no=page.page_no,
        heading_path="",
        content=text or "(This page has no text.)",
        source_tier=doc.source_tier,
        score=0.0,
        matched="both",
    )
    return ToolOutput([ctx.add_source(passage)])


class ListInput(_Input):
    pass


def _topic_lines(topics: list[Topic], parent: uuid.UUID | None, depth: int) -> list[str]:
    lines = []
    for topic in sorted((t for t in topics if t.parent_id == parent), key=lambda t: t.position):
        lines.append(f"{'  ' * depth}- {topic.title} (topic id {topic.id})")
        lines.extend(_topic_lines(topics, topic.id, depth + 1))
    return lines


async def list_materials(ctx: ToolContext, _: ListInput) -> ToolOutput:
    modules = (
        await ctx.db.execute(
            select(Module, AcademicYear.label)
            .join(AcademicYear, AcademicYear.id == Module.academic_year_id)
            .where(Module.user_id == ctx.user_id, Module.deleted_at.is_(None))
            .order_by(AcademicYear.start_date.desc(), Module.code)
        )
    ).all()
    if not modules:
        return ToolOutput("The student has no modules yet.")
    topics = list(
        (
            await ctx.db.scalars(
                select(Topic).where(Topic.user_id == ctx.user_id, Topic.deleted_at.is_(None))
            )
        ).all()
    )
    docs = list(
        (
            await ctx.db.scalars(
                select(Document)
                .where(Document.user_id == ctx.user_id, Document.deleted_at.is_(None))
                .order_by(Document.week.nulls_last(), Document.original_filename)
            )
        ).all()
    )
    lines: list[str] = []
    for module, year in modules:
        status = ", archived" if module.status == "archived" else ""
        lines.append(f"## {module.code} {module.title} ({year}{status}; module id {module.id})")
        own = [t for t in topics if t.module_id == module.id]
        lines.append("Topics:" if own else "Topics: none")
        lines.extend(_topic_lines(own, None, 1))
        files = [d for d in docs if d.module_id == module.id]
        lines.append("Files:" if files else "Files: none")
        for d in files:
            week = f", week {d.week}" if d.week is not None else ""
            pages = f", {d.page_count} pages" if d.page_count else ""
            tier = "university" if d.source_tier == "university" else "own notes"
            ready = "" if d.status == "ready" else f", {d.status}"
            lines.append(
                f"  - {d.original_filename} ({d.material_kind}{week}{pages}, {tier}{ready}; "
                f"file id {d.id})"
            )
    return ToolOutput("\n".join(lines))


class ProgressInput(_Input):
    pass


async def get_progress(ctx: ToolContext, args: ProgressInput) -> ToolOutput:
    """Measured progress: weakest topics, due flashcards, recurring mistakes."""
    # Imported here: learning -> quizzes -> marking -> generation -> chat -> tools.
    from app.services.learning import LearningService

    service = LearningService(ctx.db, ctx.user_id, ctx.client, config=ctx.config, jobs=_NoJobs())
    lines = []
    weak = await service.weakest(6)
    if weak:
        lines.append("Weakest topics (estimated strength, from marked answers):")
        for row, code, title in weak:
            days = f"last practised {row.last_practised_at:%d %b}" if row.last_practised_at else ""
            low = (
                ", little data"
                if row.weight < ctx.config.learning.mastery.low_data_weight_threshold
                else ""
            )
            lines.append(
                f"- {code} {title}: {round(row.strength * 100)}% over {row.attempts} answers{low}"
                + (f"; {days}" if days else "")
            )
    else:
        lines.append("No marked answers yet, so no topic strengths.")
    _, counts = await service.due(None)
    lines.append(
        f"Flashcards due now: {counts['due']} ({counts['new']} new, {counts['review']} review)."
    )
    recurring = [g for g in await service.mistakes(None) if g.recurring]
    if recurring:
        lines.append("Recurring mistakes (in the last 30 days):")
        lines += [f"- {g.label} in {g.topic_title}: {g.recent} times" for g in recurring[:5]]
    plan = await service.plan(None)
    if plan.questions:
        lines.append(
            f"Today's daily quiz would have {plan.questions} questions, mostly on: "
            + ", ".join(f"{b.title} ({b.allocated})" for b in plan.chosen[:4])
            + "."
        )
    return ToolOutput("\n".join(lines))


class _NoJobs:
    async def enqueue(self, function: str, *args: object, job_id: str | None = None) -> None:
        raise RuntimeError("reading progress queues no jobs")


# --- draft tools (preview before anything is saved) --------------------------------------

MaterialKindName = Literal[
    "guide",
    "summary",
    "formula_sheet",
    "worked_examples",
    "definitions",
    "explanation",
    "concept_map",
    "notes",
]


class DraftInput(_Input):
    kind: Literal["material", "questions", "flashcards"]
    module_code: str = Field(max_length=20, description="The module, e.g. MATH101.")
    topic: str | None = Field(
        default=None, max_length=200, description="A topic title in that module, if any."
    )
    material_kind: MaterialKindName | None = Field(
        default=None, description="For a material: what kind."
    )
    count: int | None = Field(default=None, ge=1, le=20, description="Questions or cards.")
    difficulty: Literal["easy", "medium", "hard", "exam", "mixed"] | None = None
    instructions: str | None = Field(
        default=None, max_length=1000, description="What to focus on, in the student's words."
    )


DRAFT_LABELS = {
    "material": "revision material",
    "questions": "questions",
    "flashcards": "flashcards",
}


async def start_draft(ctx: ToolContext, args: DraftInput) -> ToolOutput:
    # Imported here: drafts -> quizzes -> marking -> generation -> chat -> tools.
    from app.schemas.practice import GenerateRequest
    from app.services.drafts import DraftService

    if ctx.jobs is None:
        return ToolOutput("Drafts cannot be started from here.", True)
    module = await _module_by_code(ctx, args.module_code)
    if module is None:
        return ToolOutput(f"No module with code {args.module_code}.", True)
    topic_id = None
    if args.topic:
        topic = await ctx.db.scalar(
            select(Topic).where(
                Topic.user_id == ctx.user_id,
                Topic.module_id == module.id,
                Topic.deleted_at.is_(None),
                func.lower(Topic.title) == args.topic.strip().lower(),
            )
        )
        if topic is None:
            return ToolOutput(f"No topic called “{args.topic}” in {module.code}.", True)
        topic_id = topic.id
    service = DraftService(ctx.db, ctx.user_id, ctx.client, config=ctx.config, jobs=ctx.jobs)
    draft = await service.create(
        GenerateRequest(
            module_id=module.id,
            topic_id=topic_id,
            kind=args.kind,
            material_kind=args.material_kind,
            count=args.count,
            difficulty=args.difficulty,
            instructions=args.instructions,
        )
    )
    label = f"{module.code} {DRAFT_LABELS[args.kind]}" + (f": {args.topic}" if args.topic else "")
    ctx.links.append({"kind": "draft", "id": str(draft.id), "label": label})
    return ToolOutput(
        f"Started a draft of {DRAFT_LABELS[args.kind]} for {module.code}. It takes about a "
        "minute. The student sees a link to preview it, then chooses whether to save, edit, "
        "regenerate or discard it; nothing is saved until they do."
    )


# --- destructive tools (pending actions only) ---------------------------------------


class DeleteDocumentInput(_Input):
    document_id: uuid.UUID


class DeleteTopicInput(_Input):
    topic_id: uuid.UUID


class DeleteModuleInput(_Input):
    module_id: uuid.UUID


AWAITING = (
    "Deletion requested. The student now sees a confirmation card; nothing has been deleted. "
    "It happens only if they confirm it themselves within {minutes} minutes."
)


async def _request(ctx: ToolContext, kind: str, target_id: uuid.UUID) -> ToolOutput:
    service = PendingActionService(ctx.db, ctx.user_id, ctx.client, config=ctx.config)
    request = getattr(service, f"request_delete_{kind}")
    try:
        action = await request(target_id, ctx.conversation_id, ctx.message_id)
    except AppError as exc:
        return ToolOutput(exc.message, True)
    ctx.actions.append(action)
    return ToolOutput(AWAITING.format(minutes=ctx.config.ai.chat.pending_action_minutes))


async def request_delete_document(ctx: ToolContext, args: DeleteDocumentInput) -> ToolOutput:
    return await _request(ctx, "document", args.document_id)


async def request_delete_topic(ctx: ToolContext, args: DeleteTopicInput) -> ToolOutput:
    return await _request(ctx, "topic", args.topic_id)


async def request_delete_module(ctx: ToolContext, args: DeleteModuleInput) -> ToolOutput:
    return await _request(ctx, "module", args.module_id)


TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in (
        Tool(
            "search_materials",
            "Search the student's uploaded materials (lecture notes, slides, problem sheets "
            "and their own notes) by meaning and keywords. Returns the best passages, each "
            "titled with its file and page.",
            "read",
            SearchInput,
            search_materials,
            lambda a: (
                f"Searching {a.module_code + ' ' if a.module_code else 'your '}"
                f"materials for “{a.query}”"
            ),
        ),
        Tool(
            "read_page",
            "Read the full text of one page of an uploaded file, e.g. to see a whole proof "
            "or worked example that a passage only starts.",
            "read",
            ReadPageInput,
            read_page,
            lambda a: f"Reading page {a.page_no}",
        ),
        Tool(
            "list_materials",
            "List the student's modules (with academic year), each module's topic tree and "
            "its uploaded files, with ids.",
            "read",
            ListInput,
            list_materials,
            lambda _: "Looking at your modules and files",
        ),
        Tool(
            "get_progress",
            "The student's measured progress: weakest topics with estimated strength and "
            "evidence, flashcards due, recurring mistakes, and what today's daily quiz would "
            "cover. Use it for questions about how they are doing or what to revise.",
            "read",
            ProgressInput,
            get_progress,
            lambda _: "Looking at your progress",
        ),
        Tool(
            "start_draft",
            "Generate revision material (a guide, summary, formula sheet, worked examples, "
            "definitions...), practice questions or flashcards from the student's materials, "
            "as a draft they preview before saving. Use it when they ask you to make or "
            "create one of these.",
            "draft",
            DraftInput,
            start_draft,
            lambda a: f"Starting a {DRAFT_LABELS[a.kind]} draft",
        ),
        Tool(
            "request_delete_document",
            "Ask the student to confirm deleting one uploaded file. Does not delete anything.",
            "destructive",
            DeleteDocumentInput,
            request_delete_document,
            lambda _: "Asking you to confirm a deletion",
        ),
        Tool(
            "request_delete_topic",
            "Ask the student to confirm deleting a topic and its subtopics. Does not delete "
            "anything.",
            "destructive",
            DeleteTopicInput,
            request_delete_topic,
            lambda _: "Asking you to confirm a deletion",
        ),
        Tool(
            "request_delete_module",
            "Ask the student to confirm deleting a whole module. Does not delete anything.",
            "destructive",
            DeleteModuleInput,
            request_delete_module,
            lambda _: "Asking you to confirm a deletion",
        ),
    )
}


def definitions() -> list[dict[str, Any]]:
    return [tool.definition() for tool in TOOLS.values()]


@dataclass(frozen=True)
class PreparedCall:
    tool: Tool | None
    args: BaseModel | None
    error: str | None

    @property
    def status(self) -> str | None:
        return self.tool.status(self.args) if self.tool and self.args else None


def prepare(name: str, raw_input: Any) -> PreparedCall:
    """Validate a tool call's input before anything runs."""
    tool = TOOLS.get(name)
    if tool is None:
        return PreparedCall(None, None, f"There is no tool called {name}.")
    try:
        return PreparedCall(tool, tool.input_model.model_validate(raw_input), None)
    except ValidationError as exc:
        return PreparedCall(tool, None, f"Invalid input for {name}: {exc.errors()[0]['msg']}")


async def run(ctx: ToolContext, call: PreparedCall) -> ToolOutput:
    if call.tool is None or call.args is None:
        return ToolOutput(call.error or "Invalid tool call.", True)
    try:
        return await call.tool.handler(ctx, call.args)
    except AppError as exc:
        return ToolOutput(exc.message, True)
