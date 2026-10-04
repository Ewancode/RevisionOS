"""Runs a student's Python and an exercise's tests, in Pyodide (in the
browser). The backend's tests run this same file under CPython.

Inputs (set as globals by the caller): `__user_code` (str), `__tests_json`
(JSON list of {name, code}), `__mode` ("run" or "test").

Returns (the last expression) a JSON string:
{"error": str | None, "tests": [{"name", "passed", "message"}]}

A test is code run after the student's, in a copy of the same namespace; it
passes unless it raises. Output printed by the code is captured by the caller
(Pyodide's setStdout), not here.
"""

import json
import traceback


def __revision_os_run(user_code: str, tests_json: str, mode: str) -> str:
    def describe(exc: BaseException, filename: str) -> str:
        """The exception and the line of the student's code it came from."""
        lines = traceback.format_exception_only(type(exc), exc)
        frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == filename]
        where = f" (line {frames[-1].lineno})" if frames else ""
        return "".join(lines).strip() + where

    namespace: dict[str, object] = {"__name__": "__main__"}
    out: dict[str, object] = {"error": None, "tests": []}
    try:
        exec(compile(user_code, "<your code>", "exec"), namespace)  # noqa: S102 - the point
    except SyntaxError as exc:
        out["error"] = f"SyntaxError on line {exc.lineno}: {exc.msg}"
    except BaseException as exc:  # noqa: BLE001 - report anything the student's code raises
        out["error"] = describe(exc, "<your code>")
    if mode != "test":
        return json.dumps(out)

    results = []
    for test in json.loads(tests_json):
        name = test["name"]
        if out["error"] is not None:
            results.append(
                {"name": name, "passed": False, "message": "Your code raised an error first."}
            )
            continue
        filename = f"<test: {name}>"
        try:
            exec(compile(test["code"], filename, "exec"), dict(namespace))  # noqa: S102
            results.append({"name": name, "passed": True, "message": ""})
        except AssertionError as exc:
            results.append(
                {"name": name, "passed": False, "message": str(exc) or "An assertion failed."}
            )
        except BaseException as exc:  # noqa: BLE001
            message = describe(exc, "<your code>") or "".join(
                traceback.format_exception_only(type(exc), exc)
            ).strip()
            results.append({"name": name, "passed": False, "message": message})
    out["tests"] = results
    return json.dumps(out)


__revision_os_run(__user_code, __tests_json, __mode)  # noqa: F821 - set by the caller
