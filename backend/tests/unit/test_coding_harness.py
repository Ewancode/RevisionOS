"""The Python test harness the browser runs in Pyodide, run here under
CPython: it must mark code the same way in both."""

import json
from pathlib import Path
from typing import Any

HARNESS = (
    Path(__file__).resolve().parents[3] / "frontend/src/features/coding/runtime/harness.py"
).read_text(encoding="utf-8")


def run(code: str, tests: list[tuple[str, str]], mode: str = "test") -> dict[str, Any]:
    """As Pyodide does: set the globals, run the file, take the last value."""
    scope: dict[str, Any] = {
        "__user_code": code,
        "__tests_json": json.dumps([{"name": n, "code": c} for n, c in tests]),
        "__mode": mode,
    }
    body, last = HARNESS.rsplit("\n__revision_os_run(", 1)
    exec(compile(body, "<harness>", "exec"), scope)  # noqa: S102
    result: str = eval("__revision_os_run(" + last, scope)  # noqa: S307
    parsed: dict[str, Any] = json.loads(result)
    return parsed


SOLUTION = "def mean(xs):\n    return sum(xs) / len(xs) if xs else 0.0\n"
TESTS = [
    ("averages a list", "assert mean([1, 2, 3]) == 2, 'mean([1, 2, 3]) should be 2'"),
    ("handles an empty list", "assert mean([]) == 0.0"),
]


def test_a_correct_solution_passes_every_test() -> None:
    assert run(SOLUTION, TESTS) == {
        "error": None,
        "tests": [
            {"name": "averages a list", "passed": True, "message": ""},
            {"name": "handles an empty list", "passed": True, "message": ""},
        ],
    }


def test_failures_say_why() -> None:
    wrong = "def mean(xs):\n    return sum(xs) / len(xs)\n"
    result = run(wrong, TESTS)
    first, second = result["tests"]
    assert first["passed"] and not second["passed"]
    assert second["message"] == "ZeroDivisionError: division by zero (line 2)"
    off = run("def mean(xs):\n    return 0\n", TESTS)
    assert off["tests"][0]["message"] == "mean([1, 2, 3]) should be 2"
    assert off["tests"][1]["passed"]


def test_broken_code_fails_every_test_with_the_error() -> None:
    result = run("def mean(xs)\n    return 1\n", TESTS)
    assert result["error"].startswith("SyntaxError on line 1")
    assert all(not t["passed"] for t in result["tests"])
    crash = run("x = 1\nraise ValueError('bad input')\n", TESTS)
    assert crash["error"] == "ValueError: bad input (line 2)"


def test_tests_do_not_leak_into_each_other() -> None:
    tests = [
        ("sets a name", "leaked = 1"),
        ("sees a clean namespace", "assert 'leaked' not in dir()"),
    ]
    assert all(t["passed"] for t in run("", tests)["tests"])


def test_run_mode_runs_only_your_code() -> None:
    assert run(SOLUTION, TESTS, mode="run") == {"error": None, "tests": []}
