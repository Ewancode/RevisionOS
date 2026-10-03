"""Safe parsing and comparison of maths typed as text (ARCHITECTURE.md section 10).

SymPy's parser evaluates Python, so input is tokenised first and only
numbers, operators, brackets, an allow-list of functions and constants, and
the question's declared variables get through. Nothing else - no quotes,
attribute access, indexing or dunder names - ever reaches the parser.

Equivalence is decided numerically: both expressions are evaluated at random
points and must agree everywhere they are defined. That is robust where
symbolic simplification is slow or inconclusive.
"""

import cmath
import math
import random
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import sympy
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from app.core.config import MarkingConfig

TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+)|(?P<name>[A-Za-z][A-Za-z0-9]*)"
    r"|(?P<op>\*\*|[-+*/^(),!]))"
)

# Names anyone may use, in answers and in a question's check expression.
FUNCTIONS: dict[str, Any] = {
    "sin": sympy.sin, "cos": sympy.cos, "tan": sympy.tan,
    "sec": sympy.sec, "csc": sympy.csc, "cot": sympy.cot,
    "asin": sympy.asin, "acos": sympy.acos, "atan": sympy.atan,
    "arcsin": sympy.asin, "arccos": sympy.acos, "arctan": sympy.atan,
    "sinh": sympy.sinh, "cosh": sympy.cosh, "tanh": sympy.tanh,
    "exp": sympy.exp, "log": sympy.log, "ln": sympy.log, "sqrt": sympy.sqrt,
    "abs": sympy.Abs, "factorial": sympy.factorial, "binomial": sympy.binomial,
    "floor": sympy.floor, "ceiling": sympy.ceiling,
}  # fmt: skip
CONSTANTS: dict[str, Any] = {"pi": sympy.pi, "e": sympy.E, "E": sympy.E}
# Only in check expressions written by the question's author (Claude), to
# recompute a numerical answer: calculus and exact fractions.
CHECK_ONLY: dict[str, Any] = {
    "integrate": sympy.integrate, "diff": sympy.diff, "limit": sympy.limit,
    "Rational": sympy.Rational, "oo": sympy.oo,
}  # fmt: skip

TRANSFORMS = (*standard_transformations, implicit_multiplication_application, convert_xor)
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,15}$")
MAX_CHARS = 500


class MathsError(ValueError):
    """Input that is not acceptable maths; the message is shown to the student."""


def _names(text: str) -> Iterable[str]:
    position = 0
    text = text.rstrip()
    while position < len(text):
        match = TOKEN.match(text, position)
        if match is None or match.end() == position:
            raise MathsError(f"Unexpected character “{text[position:].strip()[:1]}”.")
        if match.group("name"):
            yield match.group("name")
        position = match.end()


def parse(text: str, variables: Iterable[str] = (), *, check: bool = False) -> sympy.Expr:
    """Parse `text` into a SymPy expression, refusing anything outside the
    allow-list. `check=True` also allows calculus functions (for the
    question author's check expressions, never for student answers)."""
    text = text.strip()
    if not text:
        raise MathsError("Enter an expression.")
    if len(text) > MAX_CHARS:
        raise MathsError("That expression is too long.")
    symbols = {v: sympy.Symbol(v) for v in variables}
    allowed: dict[str, Any] = {**FUNCTIONS, **CONSTANTS, **symbols}
    if check:
        allowed.update(CHECK_ONLY)
    for name in _names(text):
        if name in allowed:
            continue
        if check and IDENTIFIER.match(name):
            # A bound variable, as in integrate(t**2, (t, 0, 3)); the
            # result must still be a plain number (see `number`).
            symbols[name] = allowed[name] = sympy.Symbol(name)
            continue
        # "xy" or "2ab": a run of single-letter variables multiplied together.
        if all(ch in symbols for ch in name):
            continue
        raise MathsError(f"Unknown name “{name}”.")
    try:
        result = parse_expr(
            text,
            local_dict=allowed,
            global_dict={
                "__builtins__": {},
                "Integer": sympy.Integer,
                "Float": sympy.Float,
                "Rational": sympy.Rational,
                "Symbol": sympy.Symbol,
            },
            transformations=TRANSFORMS,
        )
    except (SyntaxError, TypeError, ValueError, AttributeError, sympy.SympifyError) as exc:
        raise MathsError("That is not a valid expression.") from exc
    if not isinstance(result, sympy.Expr):
        raise MathsError("That is not a valid expression.")
    unknown = {str(s) for s in result.free_symbols} - set(symbols)
    if unknown:
        raise MathsError(f"Unknown name “{sorted(unknown)[0]}”.")
    return result


def number(text: str, *, check: bool = False) -> float:
    """A real number, from "0.75", "3/4", "sqrt(2)/2", "1.2e-3", "pi/4"..."""
    expr = parse(text, check=check)
    try:
        value = complex(sympy.N(expr, 30))
    except (TypeError, ValueError) as exc:
        raise MathsError("That does not evaluate to a number.") from exc
    if abs(value.imag) > 1e-12 * max(1.0, abs(value.real)) or not math.isfinite(value.real):
        raise MathsError("That does not evaluate to a real number.")
    return value.real


def within(value: float, target: float, absolute: float | None, relative: float | None) -> bool:
    """`value` matches `target` within the absolute or relative tolerance."""
    gap = abs(value - target)
    if absolute is not None and gap <= absolute:
        return True
    if relative is not None and gap <= relative * abs(target):
        return True
    return gap == 0.0


@dataclass(frozen=True)
class Equivalence:
    equal: bool
    # False when too few points could be evaluated to decide either way.
    conclusive: bool


def _evaluate(expr: sympy.Expr, point: dict[sympy.Symbol, float]) -> complex | None:
    try:
        value = complex(sympy.N(expr.subs(point), 20))
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
    if not (cmath.isfinite(value)):
        return None
    return value


def equivalent(
    answer: str, expected: str, variables: list[str], config: MarkingConfig, seed: int = 0
) -> Equivalence:
    """Do `answer` and `expected` agree at random points? Raises MathsError
    if the student's answer cannot be read."""
    target = parse(expected, variables)
    given = parse(answer, variables)
    symbols = [sympy.Symbol(v) for v in variables]
    rng = random.Random(seed)  # noqa: S311 - sample points, not security
    agreed = 0
    for _ in range(config.spot_check_points * 3):
        point = {s: rng.choice((-1, 1)) * rng.uniform(0.3, 2.7) for s in symbols}
        a, b = _evaluate(given, point), _evaluate(target, point)
        if a is None or b is None:
            continue
        scale = max(1.0, abs(a), abs(b))
        if abs(a - b) > config.spot_check_tolerance * scale:
            return Equivalence(False, True)
        agreed += 1
        if agreed >= config.spot_check_points:
            break
    enough = agreed >= config.spot_check_min_points
    return Equivalence(enough, enough)


def valid_identifier(name: str) -> bool:
    return bool(IDENTIFIER.match(name)) and name not in FUNCTIONS and name not in CONSTANTS
