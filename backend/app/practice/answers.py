"""Question types: what each stores as its answer, what a student submits,
what the student sees before submitting, and rule-based marking
(ARCHITECTURE.md section 10, "Marking").

| Type             | Marked by                                    |
| ---------------- | -------------------------------------------- |
| multiple_choice  | exact match                                  |
| true_false       | exact match                                  |
| numerical        | tolerance (absolute or relative), units      |
| expression       | numeric equivalence at random points (SymPy) |
| short_answer     | accepted answers, else Claude (cheap model)  |
| explanation      | Claude against a rubric                      |
| derivation       | Claude against a rubric                      |
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.core.config import MarkingConfig
from app.practice import maths

QuestionType = Literal[
    "multiple_choice",
    "true_false",
    "numerical",
    "expression",
    "short_answer",
    "explanation",
    "derivation",
]
QUESTION_TYPES: tuple[str, ...] = QuestionType.__args__  # type: ignore[attr-defined]
Difficulty = Literal["easy", "medium", "hard", "exam"]
DIFFICULTIES: tuple[str, ...] = Difficulty.__args__  # type: ignore[attr-defined]
AI_MARKED = frozenset({"explanation", "derivation"})


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MultipleChoiceSpec(_Spec):
    type: Literal["multiple_choice"] = "multiple_choice"
    options: list[str]
    correct: int  # index into options


class TrueFalseSpec(_Spec):
    type: Literal["true_false"] = "true_false"
    answer: bool


class NumericalSpec(_Spec):
    type: Literal["numerical"] = "numerical"
    value: float
    tolerance: float | None = None  # absolute
    relative_tolerance: float | None = None
    unit: str | None = None
    # How the value is computed (SymPy syntax), recomputed when validating.
    check: str


class ExpressionSpec(_Spec):
    type: Literal["expression"] = "expression"
    answer: str  # SymPy syntax, e.g. "x**2*exp(x)"
    variables: list[str]


class ShortAnswerSpec(_Spec):
    type: Literal["short_answer"] = "short_answer"
    accepted: list[str]


class RubricPoint(_Spec):
    point: str
    marks: int


class ExplanationSpec(_Spec):
    type: Literal["explanation"] = "explanation"
    rubric: list[RubricPoint]
    model_answer: str


class DerivationSpec(_Spec):
    type: Literal["derivation"] = "derivation"
    rubric: list[RubricPoint]
    model_answer: str


AnswerSpec = Annotated[
    MultipleChoiceSpec
    | TrueFalseSpec
    | NumericalSpec
    | ExpressionSpec
    | ShortAnswerSpec
    | ExplanationSpec
    | DerivationSpec,
    Field(discriminator="type"),
]
SPEC = TypeAdapter[AnswerSpec](AnswerSpec)


def load_spec(data: dict[str, Any]) -> AnswerSpec:
    return SPEC.validate_python(data)


# --- what the student submits ---------------------------------------------------


class _Response(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ChoiceResponse(_Response):
    choice: int = Field(ge=0, le=20)


class TrueFalseResponse(_Response):
    answer: bool


class NumberResponse(_Response):
    value: str = Field(max_length=200)
    unit: str | None = Field(default=None, max_length=40)


class ExpressionResponse(_Response):
    expression: str = Field(max_length=500)


class TextResponse(_Response):
    text: str = Field(max_length=20_000)


RESPONSES: dict[str, type[_Response]] = {
    "multiple_choice": ChoiceResponse,
    "true_false": TrueFalseResponse,
    "numerical": NumberResponse,
    "expression": ExpressionResponse,
    "short_answer": TextResponse,
    "explanation": TextResponse,
    "derivation": TextResponse,
}


def load_response(question_type: str, data: dict[str, Any]) -> _Response:
    return RESPONSES[question_type].model_validate(data)


def response_text(question_type: str, response: dict[str, Any] | None) -> str:
    """The student's answer as text, for Claude to mark or explain."""
    if not response:
        return "(no answer)"
    match question_type:
        case "multiple_choice":
            return f"option {int(response['choice']) + 1}"
        case "true_false":
            return "true" if response["answer"] else "false"
        case "numerical":
            unit = response.get("unit")
            return f"{response['value']} {unit}" if unit else str(response["value"])
        case "expression":
            return str(response["expression"])
        case _:
            return str(response.get("text", ""))


# --- what the student sees before submitting --------------------------------------


def public_view(spec: AnswerSpec) -> dict[str, Any]:
    """The parts of the answer spec needed to answer, never the answer itself."""
    if isinstance(spec, MultipleChoiceSpec):
        return {"options": spec.options}
    if isinstance(spec, NumericalSpec):
        return {"unit": spec.unit}
    if isinstance(spec, ExpressionSpec):
        return {"variables": spec.variables}
    if isinstance(spec, ExplanationSpec | DerivationSpec):
        return {"marks": sum(p.marks for p in spec.rubric)}
    return {}


def correct_answer_text(spec: AnswerSpec) -> str:
    if isinstance(spec, MultipleChoiceSpec):
        return f"{spec.correct + 1}. {spec.options[spec.correct]}"
    if isinstance(spec, TrueFalseSpec):
        return "True" if spec.answer else "False"
    if isinstance(spec, NumericalSpec):
        return f"{spec.value:g}{' ' + spec.unit if spec.unit else ''}"
    if isinstance(spec, ExpressionSpec):
        return spec.answer
    if isinstance(spec, ShortAnswerSpec):
        return spec.accepted[0]
    return spec.model_answer


# --- rule-based marking ---------------------------------------------------------------


@dataclass(frozen=True)
class RuleMark:
    """A mark decided without AI, or `needs_ai` when rules cannot decide."""

    score: float = 0.0
    marked_by: Literal["rule", "sympy"] = "rule"
    feedback: str = ""
    needs_ai: bool = False
    details: dict[str, Any] = field(default_factory=dict)


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"[^\w\s.+\-*/^=]", " ", text)
    return " ".join(text.split()).strip(" .")


def _same_unit(given: str | None, expected: str | None) -> bool:
    if not expected:
        return True
    return (
        given is not None
        and given.replace(" ", "").casefold() == expected.replace(" ", "").casefold()
    )


def mark_by_rule(
    spec: AnswerSpec, response: dict[str, Any] | None, config: MarkingConfig
) -> RuleMark:
    if response is None:
        return RuleMark(0.0, feedback="Not answered.")
    if isinstance(spec, MultipleChoiceSpec):
        right = response.get("choice") == spec.correct
        return RuleMark(1.0 if right else 0.0)
    if isinstance(spec, TrueFalseSpec):
        return RuleMark(1.0 if response.get("answer") is spec.answer else 0.0)
    if isinstance(spec, NumericalSpec):
        try:
            value = maths.number(str(response.get("value", "")))
        except maths.MathsError as exc:
            return RuleMark(0.0, "sympy", f"Could not read the number: {exc}")
        relative = spec.relative_tolerance
        if spec.tolerance is None and relative is None:
            relative = config.default_relative_tolerance
        if not maths.within(value, spec.value, spec.tolerance, relative):
            return RuleMark(0.0, "sympy", details={"read_as": value})
        if not _same_unit(response.get("unit"), spec.unit):
            return RuleMark(
                0.0, "sympy", f"The number is right but the unit should be {spec.unit}."
            )
        return RuleMark(1.0, "sympy", details={"read_as": value})
    if isinstance(spec, ExpressionSpec):
        try:
            result = maths.equivalent(
                str(response.get("expression", "")), spec.answer, spec.variables, config
            )
        except maths.MathsError as exc:
            return RuleMark(0.0, "sympy", f"Could not read the expression: {exc}")
        if not result.conclusive:
            return RuleMark(needs_ai=True)  # undecidable numerically (rare)
        return RuleMark(1.0 if result.equal else 0.0, "sympy")
    if isinstance(spec, ShortAnswerSpec):
        given = normalise(str(response.get("text", "")))
        if not given:
            return RuleMark(0.0, feedback="Not answered.")
        if any(given == normalise(a) for a in spec.accepted):
            return RuleMark(1.0)
        return RuleMark(needs_ai=True)
    # explanation, derivation
    if not str(response.get("text", "")).strip():
        return RuleMark(0.0, feedback="Not answered.")
    return RuleMark(needs_ai=True)
