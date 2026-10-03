"""Deterministic checks on generated questions and flashcards (ARCHITECTURE.md
sections 8 and 13). Claude's output is never trusted to be well-formed or
right: every item is checked here, and only items that pass can be saved.

- the shape is right for the question type (Pydantic);
- multiple choice has 2-6 distinct options and exactly one correct one;
- a numerical answer is recomputed from its check expression with SymPy;
- an algebraic answer parses, using only its declared variables;
- rubrics have points worth positive marks;
- maths delimiters are balanced, so the LaTeX renders;
- every cited passage was actually supplied, and items cite at least one
  when passages were supplied (grounded in the student's materials).

Near-duplicates are checked separately, against the bank, with embeddings.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.core.config import MarkingConfig, ValidationConfig
from app.practice import maths
from app.practice.answers import (
    DIFFICULTIES,
    QUESTION_TYPES,
    AnswerSpec,
    DerivationSpec,
    ExplanationSpec,
    ExpressionSpec,
    MultipleChoiceSpec,
    NumericalSpec,
    ShortAnswerSpec,
    load_spec,
    normalise,
)

UNESCAPED_DOLLAR = re.compile(r"(?<!\\)\$")
# A model answer that only points elsewhere ("see the solution above").
REFERS_ELSEWHERE = re.compile(r"\b(see|as in|refer to)\b.{0,30}\b(solution|above|below)\b", re.I)

# The flat shape Claude fills in (structured outputs): answer fields that do
# not apply to a type are null.
_nullable_str = {"type": ["string", "null"]}
QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": list(QUESTION_TYPES)},
                    "difficulty": {"type": "string", "enum": list(DIFFICULTIES)},
                    "stem_md": {"type": "string"},
                    "solution_md": {"type": "string"},
                    "sources": {"type": "array", "items": {"type": "integer"}},
                    "options": {"type": ["array", "null"], "items": {"type": "string"}},
                    "correct_option": {"type": ["integer", "null"]},
                    "true_or_false": {"type": ["boolean", "null"]},
                    "value": {"type": ["number", "null"]},
                    "tolerance": {"type": ["number", "null"]},
                    "relative_tolerance": {"type": ["number", "null"]},
                    "unit": _nullable_str,
                    "check": _nullable_str,
                    "expression": _nullable_str,
                    "variables": {"type": ["array", "null"], "items": {"type": "string"}},
                    "accepted_answers": {"type": ["array", "null"], "items": {"type": "string"}},
                    "rubric": {
                        "type": ["array", "null"],
                        "items": {
                            "type": "object",
                            "properties": {
                                "point": {"type": "string"},
                                "marks": {"type": "integer"},
                            },
                            "required": ["point", "marks"],
                            "additionalProperties": False,
                        },
                    },
                    "model_answer": _nullable_str,
                },
                "required": [
                    "type",
                    "difficulty",
                    "stem_md",
                    "solution_md",
                    "sources",
                    "options",
                    "correct_option",
                    "true_or_false",
                    "value",
                    "tolerance",
                    "relative_tolerance",
                    "unit",
                    "check",
                    "expression",
                    "variables",
                    "accepted_answers",
                    "rubric",
                    "model_answer",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

FLASHCARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "front_md": {"type": "string"},
                    "back_md": {"type": "string"},
                    "sources": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["front_md", "back_md", "sources"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


@dataclass
class CheckedQuestion:
    raw: dict[str, Any]
    problems: list[str] = field(default_factory=list)
    spec: AnswerSpec | None = None

    @property
    def valid(self) -> bool:
        return not self.problems and self.spec is not None


@dataclass
class CheckedFlashcard:
    raw: dict[str, Any]
    problems: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.problems


def balanced_maths(text: str) -> bool:
    """An even number of unescaped `$` (so `$...$` and `$$...$$` close)."""
    return len(UNESCAPED_DOLLAR.findall(text)) % 2 == 0


def _check_sources(sources: Any, passages: int, problems: list[str]) -> None:
    if not isinstance(sources, list) or not all(isinstance(s, int) for s in sources):
        problems.append("sources must be a list of passage numbers")
        return
    bad = [s for s in sources if not 1 <= s <= passages]
    if bad:
        problems.append(f"cites passage {bad[0]}, which was not supplied")
    if passages and not sources:
        problems.append("cites no passage from the student's materials")


def _spec_from(raw: dict[str, Any]) -> dict[str, Any]:
    kind = raw.get("type")
    if kind == "multiple_choice":
        return {"type": kind, "options": raw.get("options"), "correct": raw.get("correct_option")}
    if kind == "true_false":
        return {"type": kind, "answer": raw.get("true_or_false")}
    if kind == "numerical":
        return {
            "type": kind,
            "value": raw.get("value"),
            "tolerance": raw.get("tolerance"),
            "relative_tolerance": raw.get("relative_tolerance"),
            "unit": raw.get("unit") or None,
            "check": raw.get("check"),
        }
    if kind == "expression":
        return {"type": kind, "answer": raw.get("expression"), "variables": raw.get("variables")}
    if kind == "short_answer":
        return {"type": kind, "accepted": raw.get("accepted_answers")}
    return {"type": kind, "rubric": raw.get("rubric"), "model_answer": raw.get("model_answer")}


def _check_spec(spec: AnswerSpec, config: ValidationConfig, marking: MarkingConfig) -> list[str]:
    problems: list[str] = []
    if isinstance(spec, MultipleChoiceSpec):
        if not config.min_options <= len(spec.options) <= config.max_options:
            problems.append(f"needs {config.min_options}-{config.max_options} options")
        if len({normalise(o) for o in spec.options}) != len(spec.options):
            problems.append("options must all be different")
        if any(not o.strip() for o in spec.options):
            problems.append("an option is empty")
        if not 0 <= spec.correct < len(spec.options):
            problems.append("the correct option is not one of the options")
        if not all(balanced_maths(o) for o in spec.options):
            problems.append("an option has unbalanced $ delimiters")
    elif isinstance(spec, NumericalSpec):
        if (spec.tolerance or 0) < 0 or (spec.relative_tolerance or 0) < 0:
            problems.append("tolerances cannot be negative")
        try:
            recomputed = maths.number(spec.check, check=True)
        except maths.MathsError as exc:
            problems.append(f"check expression does not compute: {exc}")
        else:
            relative = spec.relative_tolerance
            if spec.tolerance is None and relative is None:
                relative = marking.default_relative_tolerance
            # The stated answer must agree with its own working.
            if not maths.within(spec.value, recomputed, spec.tolerance, relative):
                problems.append(
                    f"the answer {spec.value:g} does not match its check ({recomputed:.6g})"
                )
    elif isinstance(spec, ExpressionSpec):
        if not spec.variables or not all(maths.valid_identifier(v) for v in spec.variables):
            problems.append("variables must be simple names, e.g. x or theta")
        elif len(spec.answer) > config.max_expression_chars:
            problems.append("the answer expression is too long")
        else:
            try:
                maths.parse(spec.answer, spec.variables)
            except maths.MathsError as exc:
                problems.append(f"the answer expression does not parse: {exc}")
    elif isinstance(spec, ShortAnswerSpec):
        if not spec.accepted or not all(a.strip() for a in spec.accepted):
            problems.append("needs at least one accepted answer")
    elif isinstance(spec, ExplanationSpec | DerivationSpec):
        if not 1 <= len(spec.rubric) <= config.max_rubric_points:
            problems.append(f"the rubric needs 1-{config.max_rubric_points} points")
        if any(p.marks <= 0 or not p.point.strip() for p in spec.rubric):
            problems.append("every rubric point needs a description and positive marks")
        answer = spec.model_answer.strip()
        if len(answer) < config.min_model_answer_chars or (
            len(answer) < 3 * config.min_model_answer_chars and REFERS_ELSEWHERE.search(answer)
        ):
            problems.append(
                "the model answer must be written out in full, not refer to the solution"
            )
    return problems


def check_question(
    raw: dict[str, Any],
    passages: int,
    config: ValidationConfig,
    marking: MarkingConfig,
) -> CheckedQuestion:
    checked = CheckedQuestion(raw)
    problems = checked.problems
    stem = str(raw.get("stem_md") or "")
    if not stem.strip():
        problems.append("the question is empty")
    elif len(stem) > config.max_stem_chars:
        problems.append("the question is too long")
    for name in ("stem_md", "solution_md"):
        if not balanced_maths(str(raw.get(name) or "")):
            problems.append(f"{name} has unbalanced $ delimiters")
    if not str(raw.get("solution_md") or "").strip():
        problems.append("needs a worked solution")
    if raw.get("difficulty") not in DIFFICULTIES:
        problems.append("unknown difficulty")
    _check_sources(raw.get("sources"), passages, problems)
    if raw.get("type") not in QUESTION_TYPES:
        problems.append("unknown question type")
        return checked
    try:
        spec = load_spec(_spec_from(raw))
    except ValidationError as exc:
        error = exc.errors()[0]
        where = ".".join(str(p) for p in error["loc"][1:]) or "answer"
        problems.append(f"{where}: {error['msg']}")
        return checked
    problems.extend(_check_spec(spec, config, marking))
    checked.spec = spec
    return checked


def check_flashcard(
    raw: dict[str, Any], passages: int, config: ValidationConfig
) -> CheckedFlashcard:
    checked = CheckedFlashcard(raw)
    problems = checked.problems
    for name in ("front_md", "back_md"):
        text = str(raw.get(name) or "")
        if not text.strip():
            problems.append(f"{name} is empty")
        elif len(text) > config.max_stem_chars:
            problems.append(f"{name} is too long")
        if not balanced_maths(text):
            problems.append(f"{name} has unbalanced $ delimiters")
    _check_sources(raw.get("sources"), passages, problems)
    return checked
