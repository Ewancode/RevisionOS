import { PythonRunner } from "./python";
import { RRunner } from "./r";
import type { Runner, RunnerOptions } from "./types";

export type Language = "python" | "r";

const runners = new Map<string, Runner>();

/** One runtime per language for the page's lifetime (they are slow to start). */
export function runnerFor(language: Language, options: RunnerOptions): Runner {
  const key = `${language}:${options.baseUrl}`;
  let runner = runners.get(key);
  if (!runner) {
    runner = language === "python" ? new PythonRunner(options) : new RRunner(options);
    runners.set(key, runner);
  }
  return runner;
}

/** Tests replace runtimes with fakes through this. */
export function setRunnerForTests(language: Language, baseUrl: string, runner: Runner | null): void {
  const key = `${language}:${baseUrl}`;
  if (runner) runners.set(key, runner);
  else runners.delete(key);
}
