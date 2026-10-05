"""The tutor's hint ladder (ARCHITECTURE.md section 9, "Tutor mode";
SPEC 38, 69), enforced here rather than trusted to the prompt:

1. a guiding question, 2. a hint, 3. a stronger hint, 4. the next step
worked through, 5. the full solution.

- Rungs are climbed one at a time; the server picks the next one.
- Rungs 1-4 come from Claude, whose request never contains the reference
  solution. Rung 5 is the stored solution itself, so no AI call can leak it
  early.
- A coding exercise's solution unlocks only after you have submitted an
  attempt, and never for assessed work. A quiz question stops at rung 4: its
  worked solution appears once the quiz is submitted.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import ClaudeClient, text_tokens
from app.core.config import AppConfig
from app.practice.generation import prompt

PROMPT = "tutor_hint.v4"
LEVELS = {
    1: "Guiding question",
    2: "Hint",
    3: "Stronger hint",
    4: "Next step",
    5: "Full solution",
}
LAST_AI_LEVEL = 4


@dataclass
class Problem:
    """What the tutor may see: never the reference solution."""

    kind: str  # coding | question
    title: str
    text_md: str
    work: str
    language: str | None = None
    visible_tests: list[str] = field(default_factory=list)
    results: str | None = None


def question_problem(stem_md: str, answer_spec: dict[str, Any], work: str = "") -> Problem:
    """A quiz question as the tutor sees it: the question, and its options if
    it is multiple choice; never which option is right."""
    options = answer_spec.get("options") if answer_spec.get("type") == "multiple_choice" else None
    text = stem_md + ("\n\nOptions:\n" + "\n".join(f"- {o}" for o in options) if options else "")
    return Problem(kind="question", title="Question", text_md=text, work=work)


@dataclass(frozen=True)
class Ladder:
    next_level: int | None
    top: int
    locked_reason: str | None


def ladder(
    given: Sequence[int], *, kind: str, submitted: bool = False, assessed: bool = False
) -> Ladder:
    if kind == "question":
        top, reason = (
            LAST_AI_LEVEL,
            "The worked solution appears when you submit the quiz.",
        )
    elif assessed:
        top, reason = (
            LAST_AI_LEVEL,
            "This is assessed work, so the tutor gives hints but never the solution.",
        )
    elif not submitted:
        top, reason = LAST_AI_LEVEL, "The full solution unlocks after you submit an attempt."
    else:
        top, reason = len(LEVELS), None
    reached = max(given, default=0)
    return Ladder(reached + 1 if reached < top else None, top, reason)


def request_text(
    problem: Problem, level: int, previous: Sequence[tuple[int, str]], config: AppConfig
) -> str:
    limit = config.coding.tutor.max_student_work_chars
    work = problem.work.strip()
    if len(work) > limit:
        work = work[:limit] + "\n[... cut short]"
    parts = [
        f"Rung {level} of the hint ladder: {LEVELS[level]}.",
        f"<problem>\n# {problem.title}\n\n{problem.text_md}\n</problem>",
    ]
    if problem.kind == "coding":
        parts.append(f"Language: {'Python' if problem.language == 'python' else 'R'}.")
        if problem.visible_tests:
            parts.append(
                "<tests_the_student_can_see>\n"
                + "\n\n".join(problem.visible_tests)
                + "\n</tests_the_student_can_see>"
            )
        if problem.results:
            parts.append(f"<latest_test_results>\n{problem.results}\n</latest_test_results>")
    parts.append(
        f"<student_work>\n{work}\n</student_work>"
        if work
        else "The student has not written anything yet."
    )
    keep = config.coding.tutor.history_hints
    if previous and keep:
        earlier = "\n\n".join(f"Rung {n} ({LEVELS[n]}):\n{text}" for n, text in previous[-keep:])
        parts.append(f"<hints_already_given>\n{earlier}\n</hints_already_given>")
    return "\n\n".join(parts)


async def ask(
    db: AsyncSession,
    claude: ClaudeClient,
    config: AppConfig,
    *,
    user_id: uuid.UUID,
    module_id: uuid.UUID,
    problem: Problem,
    level: int,
    previous: Sequence[tuple[int, str]],
) -> tuple[str, uuid.UUID]:
    if not 1 <= level <= LAST_AI_LEVEL:
        raise ValueError("Claude writes rungs 1-4 only")
    system = prompt(PROMPT)
    text = request_text(problem, level, previous, config)
    result = await claude.run(
        db,
        user_id=user_id,
        task="tutoring",
        prompt_version=PROMPT,
        system=system,
        content=[{"type": "text", "text": text}],
        estimated_input_tokens=text_tokens(system) + text_tokens(text),
        module_id=module_id,
    )
    return result.text.strip(), result.interaction_id


def solution_text(language: str, solution_code: str) -> str:
    fence = "python" if language == "python" else "r"
    return (
        "Here is a reference solution. Compare it with yours: the approach matters more "
        f"than matching it line for line.\n\n```{fence}\n{solution_code.rstrip()}\n```"
    )
