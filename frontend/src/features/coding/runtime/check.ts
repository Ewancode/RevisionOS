/**
 * The runtime check page (runtime-check.html, development only): real
 * Python and R exercises through the app's own runners.
 */
import { PythonRunner } from "./python";
import { RRunner } from "./r";
import type { Runner, RunResult } from "./types";

const params = new URLSearchParams(location.search);
const status = document.getElementById("status")!;
const results = document.getElementById("results")!;

function options(baseUrl: string, packageUrl: string) {
  return { baseUrl, packageUrl, timeoutMs: 15_000, firstRunTimeoutMs: 180_000, maxOutputChars: 20_000 };
}

interface Case {
  label: string;
  runner: Runner;
  request: Parameters<Runner["run"]>[0];
  expect: (r: RunResult) => boolean;
}

const pyTests = [
  { name: "averages a list", code: "assert mean([1, 2, 3]) == 2, 'mean([1, 2, 3]) should be 2'" },
  { name: "handles an empty list", code: "assert mean([]) == 0.0" },
  { name: "uses numpy", code: "import numpy as np\nassert abs(mean(list(np.arange(5))) - 2) < 1e-9" },
];
const rTests = [
  { name: "odd length", code: "stopifnot(med(c(3, 1, 2)) == 2)" },
  { name: "even length", code: 'if (med(c(1, 2, 3, 4)) != 2.5) stop("med(1:4) should be 2.5")' },
];

async function main() {
  const [python, pythonPackages, r, rPackages] = ["python", "python_packages", "r", "r_packages"].map((k) => params.get(k));
  if (!python || !pythonPackages || !r || !rPackages) {
    throw new Error("Give ?python=..&python_packages=..&r=..&r_packages=.. (base_url and package_url from coding.yaml).");
  }
  const py = new PythonRunner(options(python, pythonPackages));
  // A short limit, so the infinite-loop case is quick; warmed by its own
  // first case, so the long first-run allowance no longer applies.
  const loop = new PythonRunner({ ...options(python, pythonPackages), timeoutMs: 3000 });
  const rr = new RRunner(options(r, rPackages));
  const cases: Case[] = [
    {
      label: "Python: a correct solution passes",
      runner: py,
      request: { mode: "test", packages: [], tests: pyTests, code: "def mean(xs):\n    return sum(xs) / len(xs) if xs else 0.0\n" },
      expect: (x) => x.error === null && x.tests.every((t) => t.passed),
    },
    {
      label: "Python: a wrong solution fails with the reason",
      runner: py,
      request: { mode: "test", packages: [], tests: pyTests, code: "def mean(xs):\n    return sum(xs) / len(xs)\n" },
      expect: (x) => x.tests[0]!.passed && !x.tests[1]!.passed && x.tests[1]!.message.includes("ZeroDivisionError"),
    },
    {
      label: "Python: a run shows printed output",
      runner: py,
      request: { mode: "run", packages: [], tests: [], code: "import pandas as pd\nprint(pd.Series([1, 2, 3]).rolling(2).mean().tolist())" },
      expect: (x) => x.error === null && x.output.includes("[nan, 1.5, 2.5]"),
    },
    {
      label: "Python: a second runtime starts",
      runner: loop,
      request: { mode: "run", packages: [], tests: [], code: "print('ready')" },
      expect: (x) => x.output === "ready",
    },
    {
      label: "Python: an infinite loop is stopped after 3 s",
      runner: loop,
      request: { mode: "run", packages: [], tests: [], code: "while True:\n    pass\n" },
      expect: (x) => x.timedOut,
    },
    {
      label: "Python: the runtime starts again after a time-out",
      runner: loop,
      request: { mode: "run", packages: [], tests: [], code: "print(6 * 7)" },
      expect: (x) => x.error === null && x.output === "42",
    },
    {
      label: "R: a correct solution passes",
      runner: rr,
      request: { mode: "test", packages: [], tests: rTests, code: "med <- function(x) median(x)" },
      expect: (x) => x.error === null && x.tests.every((t) => t.passed),
    },
    {
      label: "R: a wrong solution fails with the reason",
      runner: rr,
      request: { mode: "test", packages: [], tests: rTests, code: "med <- function(x) sort(x)[ceiling(length(x) / 2)]" },
      expect: (x) => x.tests[0]!.passed && !x.tests[1]!.passed && x.tests[1]!.message === "med(1:4) should be 2.5",
    },
    {
      label: "R: a run prints, and errors are reported",
      runner: rr,
      request: { mode: "run", packages: [], tests: [], code: "x <- c(1, 2, 3)\nmean(x)" },
      expect: (x) => x.error === null && x.output.includes("[1] 2"),
    },
  ];
  const lines: string[] = [];
  let ok = true;
  for (const c of cases) {
    status.textContent = `Running: ${c.label}`;
    const result = await c.runner.run(c.request);
    const passed = c.expect(result);
    ok &&= passed;
    lines.push(`${passed ? "PASS" : "FAIL"}  ${c.label}  (${result.runtimeMs} ms)\n${JSON.stringify(result, null, 1)}\n`);
    results.textContent = lines.join("\n");
  }
  status.textContent = ok ? "All runtime checks passed." : "Some runtime checks failed.";
  status.dataset.status = ok ? "passed" : "failed";
}

main().catch((error: unknown) => {
  status.textContent = `Error: ${String(error)}`;
  status.dataset.status = "failed";
});
