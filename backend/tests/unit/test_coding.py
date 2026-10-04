"""Exercise checks and the hint ladder's rules."""

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from app.coding import tutor
from app.coding.validation import check_exercise
from app.core.config import get_config

LIMITS = get_config().coding.limits


def exercise(**changes: Any) -> dict[str, Any]:
    return {
        "language": "python",
        "difficulty": "medium",
        "title": "Rolling volatility",
        "prompt_md": "Write `vol(returns, window)`.",
        "starter_code": "def vol(returns, window):\n    raise NotImplementedError\n",
        "solution_code": "def vol(returns, window):\n    return 0.0\n",
        "tests": [
            {"name": "zero for flat returns", "code": "assert vol([0, 0], 2) == 0", "hidden": False}
        ],
        "packages": ["pandas"],
        "sources": [],
        **changes,
    }


def test_a_well_formed_exercise_passes() -> None:
    assert check_exercise(exercise(), 0, LIMITS).problems == []


def test_problems_are_named() -> None:
    def problems(**changes: Any) -> list[str]:
        return check_exercise(exercise(**changes), 2, LIMITS).problems

    assert problems(language="matlab") == ["The language must be Python or R."]
    assert problems(tests=[]) == ["There are no tests."]
    assert problems(tests=[{"name": "a", "code": "assert True", "hidden": True}]) == [
        "At least one test must be visible, so you know what is expected."
    ]
    assert problems(
        tests=[
            {"name": "a", "code": "assert True", "hidden": False},
            {"name": "a", "code": "assert 1 ==", "hidden": False},
        ]
    ) == [
        'Two tests are called "a".',
        'Test "a" has a Python syntax error on line 1: invalid syntax.',
    ]
    assert problems(starter_code=exercise()["solution_code"]) == [
        "The starter code is already the solution."
    ]
    assert problems(packages=["pandas; rm -rf /"]) == [
        "These are not package names: pandas; rm -rf /."
    ]
    assert problems(sources=[3]) == ["It cites a passage that was not supplied."]
    assert problems(
        tests=[{"name": "x", "code": "a" * (LIMITS.max_test_chars + 1), "hidden": False}]
    ) == [f'Test "x" is longer than {LIMITS.max_test_chars} characters.']


def test_r_is_not_parsed_on_the_server() -> None:
    r = exercise(
        language="r",
        starter_code="vol <- function(r, w) stop('todo')",
        solution_code="vol <- function(r, w) sd(r)",
        tests=[{"name": "flat", "code": "stopifnot(vol(c(0, 0), 2) == 0)", "hidden": False}],
    )
    assert check_exercise(r, 0, LIMITS).problems == []


@given(
    st.lists(st.integers(min_value=1, max_value=5), unique=True),
    st.sampled_from(["coding", "question"]),
    st.booleans(),
    st.booleans(),
)
def test_the_ladder_never_skips_and_never_leaks(
    given_levels: list[int], kind: str, submitted: bool, assessed: bool
) -> None:
    state = tutor.ladder(given_levels, kind=kind, submitted=submitted, assessed=assessed)
    reached = max(given_levels, default=0)
    if state.next_level is not None:
        assert state.next_level == reached + 1 <= state.top
    else:
        assert reached >= state.top
    # The solution (rung 5) only for a coding exercise you have attempted
    # that is not assessed.
    assert (state.top == 5) == (kind == "coding" and submitted and not assessed)
    assert (state.locked_reason is None) == (state.top == 5)


def test_the_request_holds_the_rung_but_not_the_solution() -> None:
    problem = tutor.Problem(
        kind="coding", title="T", text_md="Do it.", work="x" * 7000, language="r",
        visible_tests=["stopifnot(f(1) == 1)"], results="1 of 2 passed",
    )  # fmt: skip
    text = tutor.request_text(problem, 3, [(1, "Q?"), (2, "H.")], get_config())
    assert text.startswith("Rung 3 of the hint ladder: Stronger hint.")
    assert "Language: R." in text and "stopifnot(f(1) == 1)" in text and "1 of 2 passed" in text
    assert "[... cut short]" in text
    assert "Rung 1 (Guiding question):\nQ?" in text
    assert "solution" not in problem.__dict__
