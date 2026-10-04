import { CheckCircle2, Clock, XCircle } from "lucide-react";

import type { RunResult } from "./runtime/types";

/** Output and test results of a run. Hidden tests show only pass or fail. */
export function ResultsPanel({
  result,
  hidden,
}: {
  result: RunResult;
  /** Names of hidden tests: their names and messages are not shown. */
  hidden: Set<string>;
}) {
  const passed = result.tests.filter((t) => t.passed).length;
  let hiddenNo = 0;
  return (
    <section aria-label="Results" className="flex flex-col gap-2">
      {result.timedOut && (
        <p role="alert" className="flex items-center gap-1 text-sm text-danger">
          <Clock size={14} /> {result.error}
        </p>
      )}
      {!result.timedOut && result.error && (
        <pre role="alert" className="overflow-x-auto whitespace-pre-wrap rounded-md bg-surface p-2 text-xs text-danger">
          {result.error}
        </pre>
      )}
      {result.tests.length > 0 && (
        <>
          <p className="text-sm font-medium" role="status">
            {passed} of {result.tests.length} tests passed
          </p>
          <ul aria-label="Tests" className="flex flex-col gap-1">
            {result.tests.map((t) => {
              const secret = hidden.has(t.name);
              const name = secret ? `Hidden test ${++hiddenNo}` : t.name;
              return (
                <li key={t.name} className="flex flex-col text-sm">
                  <span className="flex items-center gap-1.5">
                    {t.passed ? (
                      <CheckCircle2 size={14} className="text-success" aria-label="Passed" />
                    ) : (
                      <XCircle size={14} className="text-danger" aria-label="Failed" />
                    )}
                    {name}
                  </span>
                  {!t.passed && !secret && t.message && (
                    <span className="ml-5 font-mono text-xs text-muted">{t.message}</span>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
      {result.output && (
        <div>
          <p className="text-xs text-muted">Output</p>
          <pre aria-label="Output" className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-surface p-2 text-xs">
            {result.output}
          </pre>
        </div>
      )}
    </section>
  );
}

/** "odd list: passed; single item: failed (AssertionError)" for the tutor. */
export function resultsText(result: RunResult, hidden: Set<string>): string {
  if (result.error && !result.tests.length) return `Error: ${result.error}`;
  return result.tests
    .filter((t) => !hidden.has(t.name))
    .map((t) => `${t.name}: ${t.passed ? "passed" : `failed${t.message ? ` (${t.message})` : ""}`}`)
    .join("; ");
}
