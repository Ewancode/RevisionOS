import uuid
from datetime import datetime
from typing import Annotated, Any, ClassVar, Literal

from pydantic import Field, StringConstraints

from app.practice.answers import Difficulty, QuestionType
from app.schemas.chat import CitationOut
from app.schemas.common import Input, Output, Patch, Text200

MaterialKind = Literal[
    "guide",
    "summary",
    "formula_sheet",
    "worked_examples",
    "definitions",
    "explanation",
    "concept_map",
    "notes",
]
Origin = Literal["user", "claude"]
Markdown = Annotated[str, StringConstraints(min_length=1, max_length=200_000)]
Instructions = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]

# --- drafts (generation) --------------------------------------------------------------


class GenerateRequest(Input):
    """Ask Claude for a material, questions or flashcards. The result is a
    draft to preview before anything is saved."""

    module_id: uuid.UUID
    topic_id: uuid.UUID | None = None
    kind: Literal["material", "questions", "flashcards"]
    material_kind: MaterialKind | None = None
    instructions: Instructions | None = None
    # Questions or flashcards to write (practice.yaml generation limits).
    count: int | None = Field(default=None, ge=1)
    difficulty: Difficulty | Literal["mixed"] | None = None
    types: list[QuestionType] | None = None
    # Write from these files rather than from search results.
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    # Write an improved version of this material (never overwriting it).
    improve_material_id: uuid.UUID | None = None


class DraftOut(Output):
    id: uuid.UUID
    module_id: uuid.UUID
    topic_id: uuid.UUID | None
    kind: Literal["material", "questions", "flashcards"]
    request: dict[str, Any]
    status: Literal["generating", "ready", "failed", "saved", "discarded"]
    # material: {title, content_md, citations}
    # questions/flashcards: {items: [{..., problems, valid}], passages: [...]}
    payload: dict[str, Any] | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class DraftSave(Input):
    # Material: your edits to the preview, if any.
    title: Text200 | None = None
    content_md: Markdown | None = None
    # Questions or flashcards: which items to keep (default: every valid one).
    selected: list[int] | None = None


class DraftRegenerate(Input):
    instructions: Instructions | None = None


class SavedDraft(Output):
    draft: DraftOut
    material_id: uuid.UUID | None = None
    saved_items: int = 0


# --- materials and versions ----------------------------------------------------------


class VersionSummary(Output):
    id: uuid.UUID
    version_no: int
    created_by: Origin
    change_note: str | None
    created_at: datetime


class VersionOut(VersionSummary):
    content_md: str
    citations: list[CitationOut]


class MaterialSummary(Output):
    id: uuid.UUID
    module_id: uuid.UUID
    topic_id: uuid.UUID | None
    title: str
    kind: MaterialKind
    origin: Origin
    created_at: datetime
    updated_at: datetime


class MaterialOut(MaterialSummary):
    current: VersionOut
    versions: list[VersionSummary]


class MaterialCreate(Input):
    module_id: uuid.UUID
    topic_id: uuid.UUID | None = None
    title: Text200
    kind: MaterialKind = "notes"
    content_md: Markdown


class MaterialUpdate(Patch):
    required_fields: ClassVar[frozenset[str]] = frozenset({"title", "kind"})
    title: Text200 | None = None
    kind: MaterialKind | None = None
    topic_id: uuid.UUID | None = None


class VersionCreate(Input):
    content_md: Markdown
    change_note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = (
        None
    )


class DiffLine(Output):
    op: Literal["equal", "insert", "delete"]
    text: str


class DiffOut(Output):
    from_version: int
    to_version: int
    lines: list[DiffLine]


# --- questions --------------------------------------------------------------------------


class QuestionOut(Output):
    id: uuid.UUID
    module_id: uuid.UUID
    topic_id: uuid.UUID | None
    type: QuestionType
    difficulty: Difficulty
    stem_md: str
    answer_spec: dict[str, Any]
    solution_md: str
    origin: Origin
    status: Literal["active", "retired"]
    sources: list[dict[str, Any]]
    created_at: datetime
    attempts: int = 0
    last_score: float | None = None
    last_attempted_at: datetime | None = None


class QuestionUpdate(Patch):
    required_fields: ClassVar[frozenset[str]] = frozenset({"difficulty", "status"})
    topic_id: uuid.UUID | None = None
    difficulty: Difficulty | None = None
    status: Literal["active", "retired"] | None = None


# --- flashcards -----------------------------------------------------------------------------

CardText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class FlashcardOut(Output):
    id: uuid.UUID
    module_id: uuid.UUID
    topic_id: uuid.UUID | None
    front_md: str
    back_md: str
    origin: Origin
    sources: list[dict[str, Any]]
    created_at: datetime
    # Scheduling (FSRS): 1 learning, 2 review, 3 relearning.
    fsrs_state: int
    due: datetime
    last_review: datetime | None
    reps: int
    lapses: int


class FlashcardCreate(Input):
    module_id: uuid.UUID
    topic_id: uuid.UUID | None = None
    front_md: CardText
    back_md: CardText


class FlashcardUpdate(Patch):
    required_fields: ClassVar[frozenset[str]] = frozenset({"front_md", "back_md"})
    topic_id: uuid.UUID | None = None
    front_md: CardText | None = None
    back_md: CardText | None = None


# --- quizzes and attempts -----------------------------------------------------------------


class QuizCreate(Input):
    """Build a quiz from the bank and start it. Either name the questions, or
    give filters and a count. A mock exam is timed and runs in exam mode."""

    module_id: uuid.UUID
    kind: Literal["practice", "mock"] = "practice"
    title: Text200 | None = None
    question_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)
    topic_ids: list[uuid.UUID] | None = None
    difficulties: list[Difficulty] | None = None
    types: list[QuestionType] | None = None
    result: Literal["any", "unattempted", "wrong"] = "any"
    count: int | None = Field(default=None, ge=1)
    time_limit_minutes: int | None = Field(default=None, ge=1)


class QuizOut(Output):
    id: uuid.UUID
    # None for a daily quiz, which spans modules.
    module_id: uuid.UUID | None
    kind: Literal["practice", "mock", "daily"]
    title: str
    time_limit_minutes: int | None
    created_at: datetime


class Explanation(Output):
    why_wrong: str
    correct_answer: str
    reasoning: str
    mistake: str
    how_to_avoid: str


class AttemptItem(Output):
    position: int
    question_id: uuid.UUID
    type: QuestionType
    difficulty: Difficulty
    topic_id: uuid.UUID | None
    stem_md: str
    # What answering needs: options, unit, variables, marks. Never the answer.
    view: dict[str, Any]
    response: dict[str, Any] | None
    time_ms: int | None
    self_confidence: int | None
    has_photo: bool
    # After marking:
    question_attempt_id: uuid.UUID | None = None
    score: float | None = None
    marked_by: Literal["rule", "sympy", "ai", "override"] | None = None
    marking_confidence: Literal["high", "medium", "low"] | None = None
    feedback: dict[str, Any] | None = None
    mistake_category: str | None = None
    correct_answer: str | None = None
    solution_md: str | None = None
    sources: list[dict[str, Any]] | None = None


class Breakdown(Output):
    key: str
    label: str
    questions: int
    score: float


class AttemptSummary(Output):
    questions: int
    answered: int
    correct: int
    partial: int
    incorrect: int
    unmarked: int
    score: float | None
    time_taken_seconds: int | None
    by_difficulty: list[Breakdown]
    by_topic: list[Breakdown]
    weak_areas: list[str]
    next_steps: list[str]


class AttemptOut(Output):
    id: uuid.UUID
    quiz: QuizOut
    mode: Literal["normal", "exam"]
    status: Literal["in_progress", "marking", "marked"]
    started_at: datetime
    deadline: datetime | None
    submitted_at: datetime | None
    items: list[AttemptItem]
    summary: AttemptSummary | None = None


class AttemptListItem(Output):
    id: uuid.UUID
    quiz_id: uuid.UUID
    title: str
    kind: Literal["practice", "mock", "daily"]
    mode: Literal["normal", "exam"]
    status: Literal["in_progress", "marking", "marked"]
    started_at: datetime
    submitted_at: datetime | None
    score: float | None
    questions: int


class AttemptStarted(Output):
    quiz: QuizOut
    attempt_id: uuid.UUID


class ResponseSave(Input):
    response: dict[str, Any] | None
    time_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    self_confidence: int | None = Field(default=None, ge=1, le=5)


class PhotoTranscription(Output):
    markdown: str
    confidence: Literal["high", "medium", "low"]
    notes: str


class ScoreOverride(Input):
    score: float = Field(ge=0.0, le=1.0)
