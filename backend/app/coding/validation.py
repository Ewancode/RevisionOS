"""Checks on coding exercises, whether Claude wrote them or you did.

The server never runs your code (ARCHITECTURE.md section 1), so it checks
what it can without running anything:

- the shape: a title, a task, starter and reference code, 1-20 named tests,
  at least one test you can see, and sane package names;
- Python is *parsed* (never executed) with `ast`, so syntax errors in the
  starter, the reference solution or a test are caught;
- the starter is not already the solution;
- cited passages were actually supplied.

Whether the reference solution passes its own tests is checked in your
browser, in the draft preview, before Claude's exercises can be saved.
"""

import ast
import re
from dataclasses import dataclass, field
from typing import Any

from app.core.config import CodingLimits
from app.models.coding import LANGUAGES
from app.practice.answers import DIFFICULTIES

PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")

CODING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "language": {"type": "string", "enum": list(LANGUAGES)},
                    "difficulty": {"type": "string", "enum": list(DIFFICULTIES)},
                    "prompt_md": {"type": "string"},
                    "starter_code": {"type": "string"},
                    "solution_code": {"type": "string"},
                    "tests": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "code": {"type": "string"},
                                "hidden": {"type": "boolean"},
                            },
                            "required": ["name", "code", "hidden"],
                            "additionalProperties": False,
                        },
                    },
                    "packages": {"type": "array", "items": {"type": "string"}},
                    "sources": {"type": "array", "items": {"type": "integer"}},
                },
                "required": [
                    "title",
                    "language",
                    "difficulty",
                    "prompt_md",
                    "starter_code",
                    "solution_code",
                    "tests",
                    "packages",
                    "sources",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


@dataclass
class CheckedExercise:
    raw: dict[str, Any]
    problems: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.problems


def _python_syntax(code: str, where: str) -> str | None:
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return f"{where} has a Python syntax error on line {exc.lineno}: {exc.msg}."
    return None


def _text(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    return value if isinstance(value, str) else ""


def check_exercise(
    raw: dict[str, Any], passages: int, limits: CodingLimits, *, need_sources: bool = False
) -> CheckedExercise:
    checked = CheckedExercise(raw)
    problems = checked.problems
    language = raw.get("language")
    if language not in LANGUAGES:
        problems.append("The language must be Python or R.")
    if raw.get("difficulty") not in DIFFICULTIES:
        problems.append("The difficulty is not one of easy, medium, hard or exam.")
    title = _text(raw, "title").strip()
    if not title or len(title) > 200:
        problems.append("The title must be 1-200 characters.")
    if not _text(raw, "prompt_md").strip():
        problems.append("The task description is empty.")
    starter, solution = _text(raw, "starter_code"), _text(raw, "solution_code")
    if not solution.strip():
        problems.append("There is no reference solution.")
    for name, code in (("The starter code", starter), ("The reference solution", solution)):
        if len(code) > limits.max_code_chars:
            problems.append(f"{name} is longer than {limits.max_code_chars} characters.")
    if solution.strip() and starter.strip() == solution.strip():
        problems.append("The starter code is already the solution.")

    tests = raw.get("tests")
    if not isinstance(tests, list) or not tests:
        problems.append("There are no tests.")
        tests = []
    elif len(tests) > limits.max_tests:
        problems.append(f"There are more than {limits.max_tests} tests.")
    names: set[str] = set()
    for i, test in enumerate(tests, start=1):
        if not isinstance(test, dict):
            problems.append(f"Test {i} is malformed.")
            continue
        name = _text(test, "name").strip()
        code = _text(test, "code")
        if not name or len(name) > 100:
            problems.append(f"Test {i} needs a name of 1-100 characters.")
        elif name in names:
            problems.append(f'Two tests are called "{name}".')
        names.add(name)
        if not code.strip():
            problems.append(f'Test "{name or i}" has no code.')
        elif len(code) > limits.max_test_chars:
            problems.append(
                f'Test "{name or i}" is longer than {limits.max_test_chars} characters.'
            )
        elif language == "python" and (error := _python_syntax(code, f'Test "{name or i}"')):
            problems.append(error)
    if tests and all(isinstance(t, dict) and t.get("hidden") for t in tests):
        problems.append("At least one test must be visible, so you know what is expected.")

    if language == "python":
        for where, code in (("The starter code", starter), ("The reference solution", solution)):
            if code.strip() and (error := _python_syntax(code, where)):
                problems.append(error)

    packages = raw.get("packages") or []
    if not isinstance(packages, list) or len(packages) > limits.max_packages:
        problems.append(f"List at most {limits.max_packages} packages.")
    elif bad := [p for p in packages if not isinstance(p, str) or not PACKAGE.match(p)]:
        problems.append(f"These are not package names: {', '.join(map(str, bad))}.")

    sources = raw.get("sources") or []
    if any(not isinstance(n, int) or not 1 <= n <= passages for n in sources):
        problems.append("It cites a passage that was not supplied.")
    if need_sources and passages and not sources:
        problems.append("It does not cite any of the supplied passages.")
    return checked
