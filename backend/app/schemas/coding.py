import uuid
from datetime import datetime
from typing import Annotated, ClassVar, Literal

from pydantic import Field, StringConstraints

from app.practice.answers import Difficulty
from app.schemas.common import Input, Output, Patch, Text200

Language = Literal["python", "r"]
Code = Annotated[str, StringConstraints(max_length=20_000)]
TaskMarkdown = Annotated[str, StringConstraints(min_length=1, max_length=50_000)]
TestName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Package = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")]


class RuntimeOut(Output):
    label: str
    base_url: str
    package_url: str


class CodingConfigOut(Output):
    """What the browser needs to run code: pinned runtimes and limits."""

    runtimes: dict[str, RuntimeOut]
    run_timeout_seconds: int
    first_run_timeout_seconds: int
    max_output_chars: int


class TestCase(Input):
    name: TestName
    code: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    hidden: bool = False


class ExerciseIn(Input):
    module_id: uuid.UUID
    topic_id: uuid.UUID | None = None
    language: Language
    title: Text200
    prompt_md: TaskMarkdown
    starter_code: Code = ""
    solution_code: Code
    tests: list[TestCase] = Field(min_length=1, max_length=20)
    packages: list[Package] = Field(default_factory=list, max_length=10)
    difficulty: Difficulty = "medium"
    assessed: bool = False


class ExerciseUpdate(Patch):
    required_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "title",
            "prompt_md",
            "starter_code",
            "solution_code",
            "tests",
            "packages",
            "difficulty",
            "assessed",
        }
    )
    topic_id: uuid.UUID | None = None
    title: Text200 | None = None
    prompt_md: TaskMarkdown | None = None
    starter_code: Code | None = None
    solution_code: Code | None = None
    tests: list[TestCase] | None = Field(default=None, min_length=1, max_length=20)
    packages: list[Package] | None = Field(default=None, max_length=10)
    difficulty: Difficulty | None = None
    assessed: bool | None = None


class TestOut(Output):
    name: str
    code: str
    hidden: bool


class Progress(Output):
    submissions: int
    best_passed: int | None
    total: int
    solved: bool


class ExerciseSummary(Output):
    id: uuid.UUID
    module_id: uuid.UUID
    topic_id: uuid.UUID | None
    language: Language
    title: str
    difficulty: Difficulty
    origin: Literal["user", "claude"]
    assessed: bool
    progress: Progress
    created_at: datetime


class ExerciseOut(ExerciseSummary):
    """Everything the browser needs to run the tests. The reference solution
    is not included: it is rung 5 of the hint ladder."""

    prompt_md: str
    starter_code: str
    # Hidden tests are sent too (they run in your browser), but the page
    # shows only their names and results.
    tests: list[TestOut]
    packages: list[str]
    sources: list[dict[str, object]]
    # Your latest submitted code, to carry on from.
    latest_code: str | None


class ResultIn(Input):
    name: TestName
    passed: bool
    message: Annotated[str, StringConstraints(max_length=2000)] = ""


class SubmissionIn(Input):
    code: Code
    results: list[ResultIn] = Field(max_length=20)
    # Your code failed before any test ran (a syntax error, say).
    error: Annotated[str, StringConstraints(max_length=4000)] | None = None
    runtime_ms: int | None = Field(default=None, ge=0, le=600_000)


class SubmissionOut(Output):
    id: uuid.UUID
    code: str
    results: list[dict[str, object]]
    passed: int
    total: int
    error: str | None
    runtime_ms: int | None
    created_at: datetime


class HintRequest(Input):
    # What you have so far (code, or your written answer), so the hint
    # responds to it.
    work: Annotated[str, StringConstraints(max_length=20_000)] = ""
    # The latest test results, as text, for a coding exercise.
    results: Annotated[str, StringConstraints(max_length=4000)] | None = None


class HintOut(Output):
    level: int
    label: str
    content_md: str
    created_at: datetime


class HintsOut(Output):
    hints: list[HintOut]
    next_level: int | None
    next_label: str | None
    top: int
    locked_reason: str | None
