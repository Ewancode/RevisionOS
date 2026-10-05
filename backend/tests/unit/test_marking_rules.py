"""Safe maths parsing, rule-based marking for every answer type, and the
checks on generated questions and flashcards."""

from typing import Any

import pytest

from app.core.config import get_config
from app.practice import maths
from app.practice.answers import (
    DerivationSpec,
    ExpressionSpec,
    MultipleChoiceSpec,
    NumericalSpec,
    RubricPoint,
    ShortAnswerSpec,
    TrueFalseSpec,
    load_spec,
    mark_by_rule,
    public_view,
)
from app.practice.marking import explain_schema, mark_schema
from app.practice.validation import (
    FLASHCARD_SCHEMA,
    QUESTION_SCHEMA,
    balanced_maths,
    check_flashcard,
    check_question,
)

PRACTICE = get_config().practice
FULL = "A full answer: state the definitions, then derive the result step by step."
MARKING = PRACTICE.marking


# --- maths -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [("3/4", 0.75), ("sqrt(2)/2", 2**0.5 / 2), ("1.5e3", 1500.0), ("2^10", 1024.0), ("e^0", 1.0)],
)
def test_numbers_are_read_from_maths(text: str, value: float) -> None:
    assert maths.number(text) == pytest.approx(value)


@pytest.mark.parametrize(
    "attack",
    [
        '__import__("os").system("x")',
        "x.__class__",
        "eval(1)",
        "open(1)",
        "[x for x in 1]",
        "lambda: 1",
        "x; 1",
        "getattr(x, 1)",
        "'str'",
        "x" * 600,
    ],
)
def test_nothing_but_maths_reaches_the_parser(attack: str) -> None:
    with pytest.raises(maths.MathsError):
        maths.parse(attack, ["x"])


def test_undeclared_names_are_refused() -> None:
    with pytest.raises(maths.MathsError, match="Unknown name"):
        maths.parse("x + y", ["x"])


def test_check_expressions_allow_calculus_but_must_be_numbers() -> None:
    assert maths.number("integrate(t**2, (t, 0, 3))", check=True) == pytest.approx(9)
    assert maths.number("binomial(10,3)*Rational(1,2)**10", check=True) == pytest.approx(0.1171875)
    with pytest.raises(maths.MathsError):
        maths.number("t + 1", check=True)
    # Students cannot use them.
    with pytest.raises(maths.MathsError):
        maths.number("integrate(1, (t, 0, 1))")


@pytest.mark.parametrize(
    ("answer", "equal"),
    [
        ("2x e^x + x^2 e^x", True),
        ("e^x (x^2 + 2x)", True),
        ("x^2 e^x", False),
        ("exp(x)*x*(x+2)", True),
    ],
)
def test_algebraic_answers_are_compared_by_value(answer: str, equal: bool) -> None:
    result = maths.equivalent(answer, "exp(x)*(x**2+2*x)", ["x"], MARKING)
    assert result.conclusive and result.equal is equal


def test_identities_are_equivalent() -> None:
    assert maths.equivalent("sin(x)^2 + cos(x)^2", "1", ["x"], MARKING).equal
    assert maths.equivalent("2ab", "2*a*b", ["a", "b"], MARKING).equal


# --- rule marking, per type -----------------------------------------------------------------


def _mark(spec: Any, response: dict[str, Any] | None) -> tuple[float, bool]:
    mark = mark_by_rule(spec, response, MARKING)
    return mark.score, mark.needs_ai


def test_multiple_choice_and_true_false() -> None:
    spec = MultipleChoiceSpec(options=["a", "b", "c"], correct=2)
    assert _mark(spec, {"choice": 2}) == (1.0, False)
    assert _mark(spec, {"choice": 0}) == (0.0, False)
    assert _mark(spec, None) == (0.0, False)
    assert _mark(TrueFalseSpec(answer=False), {"answer": False}) == (1.0, False)
    assert _mark(TrueFalseSpec(answer=False), {"answer": True}) == (0.0, False)


def test_numerical_tolerances_and_units() -> None:
    spec = NumericalSpec(value=0.1172, tolerance=0.0005, check="0.1172")
    assert _mark(spec, {"value": "0.117"}) == (1.0, False)
    assert _mark(spec, {"value": "15/128"}) == (1.0, False)
    assert _mark(spec, {"value": "0.12"}) == (0.0, False)
    relative = NumericalSpec(value=200.0, relative_tolerance=0.01, check="200")
    assert _mark(relative, {"value": "201.5"}) == (1.0, False)
    # No tolerance given: practice.yaml's default relative tolerance.
    default = NumericalSpec(value=100.0, check="100")
    assert _mark(default, {"value": "100.5"}) == (1.0, False)
    units = NumericalSpec(value=9.81, tolerance=0.01, unit="m/s^2", check="9.81")
    assert _mark(units, {"value": "9.81", "unit": "m / s^2"}) == (1.0, False)
    wrong_unit = mark_by_rule(units, {"value": "9.81", "unit": "km"}, MARKING)
    assert wrong_unit.score == 0.0 and "unit" in wrong_unit.feedback
    unreadable = mark_by_rule(units, {"value": "nine"}, MARKING)
    assert unreadable.score == 0.0 and "Could not read" in unreadable.feedback


def test_expressions() -> None:
    spec = ExpressionSpec(answer="x**2*exp(x)", variables=["x"])
    assert _mark(spec, {"expression": "e^x x^2"}) == (1.0, False)
    assert _mark(spec, {"expression": "2x e^x"}) == (0.0, False)
    bad = mark_by_rule(spec, {"expression": "import os"}, MARKING)
    assert bad.score == 0.0 and "Could not read" in bad.feedback


def test_short_answers_match_exactly_or_go_to_claude() -> None:
    spec = ShortAnswerSpec(accepted=["Central Limit Theorem", "CLT"])
    assert _mark(spec, {"text": "the central limit theorem."}) == (0.0, True)
    assert _mark(spec, {"text": "central limit theorem"}) == (1.0, False)
    assert _mark(spec, {"text": "clt"}) == (1.0, False)
    assert _mark(spec, {"text": "   "}) == (0.0, False)


def test_written_answers_go_to_claude_unless_blank() -> None:
    spec = DerivationSpec(rubric=[RubricPoint(point="p", marks=2)], model_answer="m")
    assert _mark(spec, {"text": "My proof..."}) == (0.0, True)
    assert _mark(spec, {"text": ""}) == (0.0, False)


def test_the_answer_is_never_shown_before_submission() -> None:
    assert public_view(MultipleChoiceSpec(options=["a", "b"], correct=1)) == {"options": ["a", "b"]}
    assert public_view(NumericalSpec(value=3.0, unit="kg", check="3")) == {"unit": "kg"}
    assert public_view(ExpressionSpec(answer="x**2", variables=["x"])) == {"variables": ["x"]}
    assert public_view(ShortAnswerSpec(accepted=["secret"])) == {}
    spec = DerivationSpec(rubric=[RubricPoint(point="p", marks=2)], model_answer="secret")
    assert public_view(spec) == {"marks": 2}


# --- checks on generated items ---------------------------------------------------------------


def item(type_: str, **fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": type_,
        "difficulty": "medium",
        "stem_md": "What is $x$?",
        "solution_md": "Because $x = 1$.",
        "sources": [1],
        **dict.fromkeys(
            [
                "options", "correct_option", "true_or_false", "value", "tolerance",
                "relative_tolerance", "unit", "check", "expression", "variables",
                "accepted_answers", "rubric", "model_answer",
            ]
        ),
    }  # fmt: skip
    return base | fields


def _problems(raw: dict[str, Any], passages: int = 3) -> list[str]:
    return check_question(raw, passages, PRACTICE.validation, MARKING).problems


VALID = [
    item("multiple_choice", options=["1", "2", "3"], correct_option=0),
    item("true_false", true_or_false=True),
    item("numerical", value=9.0, tolerance=0.01, check="integrate(t**2, (t, 0, 3))"),
    item("expression", expression="2*x*exp(x**2)", variables=["x"]),
    item("short_answer", accepted_answers=["Rolle's theorem"]),
    item("explanation", rubric=[{"point": "States it", "marks": 1}], model_answer=FULL),
    item(
        "derivation",
        rubric=[{"point": "Product rule", "marks": 2}, {"point": "Simplifies", "marks": 1}],
        model_answer=FULL,
    ),
]


@pytest.mark.parametrize("raw", VALID, ids=[v["type"] for v in VALID])
def test_valid_questions_pass(raw: dict[str, Any]) -> None:
    checked = check_question(raw, 3, PRACTICE.validation, MARKING)
    assert checked.problems == [] and checked.valid
    assert load_spec(checked.spec.model_dump()) == checked.spec  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("raw", "problem"),
    [
        (item("multiple_choice", options=["1", "1 "], correct_option=0), "different"),
        (item("multiple_choice", options=["1", "2"], correct_option=2), "not one of the options"),
        (item("multiple_choice", options=["1"], correct_option=0), "options"),
        (item("multiple_choice", options=None, correct_option=0), "options"),
        (item("numerical", value=10.0, tolerance=0.01, check="9"), "does not match its check"),
        (item("numerical", value=9.0, check="import os"), "does not compute"),
        (item("expression", expression="x + y", variables=["x"]), "does not parse"),
        (item("expression", expression="x", variables=["sin"]), "simple names"),
        (item("short_answer", accepted_answers=[]), "accepted answer"),
        (item("derivation", rubric=[{"point": "p", "marks": 0}], model_answer="m"), "positive"),
        (item("explanation", rubric=[], model_answer=FULL), "rubric"),
        (
            item(
                "explanation",
                rubric=[{"point": "p", "marks": 1}],
                model_answer="See solution above.",
            ),
            "written out in full",
        ),
        (
            item(
                "derivation",
                rubric=[{"point": "p", "marks": 1}],
                model_answer="As in the worked solution above, apply the product rule.",
            ),
            "written out in full",
        ),
        (item("true_false", true_or_false=True, stem_md="Is $x > 1?"), "unbalanced"),
        (item("true_false", true_or_false=True, sources=[7]), "not supplied"),
        (item("true_false", true_or_false=True, sources=[]), "cites no passage"),
        (item("true_false", true_or_false=True, solution_md=""), "worked solution"),
        (item("essay"), "unknown question type"),
    ],
)
def test_bad_questions_are_caught(raw: dict[str, Any], problem: str) -> None:
    problems = _problems(raw)
    assert any(problem in p for p in problems), problems


def test_flashcards_are_checked() -> None:
    good = {"front_md": "State the CLT.", "back_md": "$\\bar X$ is approx. normal", "sources": [1]}
    assert check_flashcard(good, 2, PRACTICE.validation).valid
    bad = {"front_md": "", "back_md": "$x", "sources": [3]}
    problems = check_flashcard(bad, 2, PRACTICE.validation).problems
    assert len(problems) == 3


def test_dollar_balance_ignores_escaped_dollars() -> None:
    assert balanced_maths("costs \\$5 and $x$")
    assert not balanced_maths("$x")


# --- structured-output schemas ------------------------------------------------------------


def _walk(schema: Any) -> list[dict[str, Any]]:
    if isinstance(schema, dict):
        return [schema, *[n for v in schema.values() for n in _walk(v)]]
    if isinstance(schema, list):
        return [n for v in schema for n in _walk(v)]
    return []


@pytest.mark.parametrize(
    "schema",
    [
        QUESTION_SCHEMA,
        FLASHCARD_SCHEMA,
        mark_schema(get_config().learning.mistakes.categories),
        explain_schema(get_config().learning.mistakes.categories),
    ],
    ids=["questions", "flashcards", "mark", "explain"],
)
def test_schemas_use_only_what_structured_outputs_accept(schema: dict[str, Any]) -> None:
    """The API rejects an enum on a list of types (found in a live run), and
    needs every object closed with all its properties required."""
    for node in _walk(schema):
        if "enum" in node:
            assert isinstance(node.get("type"), str), node
        if node.get("type") == "object" or node.get("type") == ["object", "null"]:
            assert node.get("additionalProperties") is False, node
            assert set(node.get("required", [])) == set(node.get("properties", {})), node


def test_a_question_that_prints_its_own_answer_is_rejected() -> None:
    """Found by the Phase 12 AI evaluation."""
    given = item(
        "expression",
        stem_md="Express $(A+B)/2 - M$ in terms of $A$, $B$ and $M$ only.",
        expression="(A+B)/2 - M",
        variables=["A", "B", "M"],
    )
    assert any("gives its own answer away" in p for p in _problems(given))
    short = item("short_answer", stem_md="Which theorem? (Hint: Rolle's theorem.)",
                 accepted_answers=["Rolle's theorem"])  # fmt: skip
    assert any("gives its own answer away" in p for p in _problems(short))
    # Short answers that could appear by chance are not checked.
    assert _problems(item("expression", stem_md="Differentiate $x^2$.", expression="2*x",
                          variables=["x"])) == []  # fmt: skip
