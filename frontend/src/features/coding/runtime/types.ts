/** What every language runtime does: run code, or run it against tests. */

export interface TestCase {
  name: string;
  code: string;
}

export interface TestResult {
  name: string;
  passed: boolean;
  message: string;
}

export interface RunResult {
  /** Everything printed, capped at the configured length. */
  output: string;
  /** Your code failed before any test ran (or, for a plain run, at all). */
  error: string | null;
  tests: TestResult[];
  runtimeMs: number;
  timedOut: boolean;
}

export interface RunRequest {
  code: string;
  tests: TestCase[];
  mode: "run" | "test";
  packages: string[];
}

export interface Runner {
  /** Download and start the runtime (the first time takes a while). */
  ready(): Promise<void>;
  run(request: RunRequest): Promise<RunResult>;
  /** Stop the runtime; the next run starts a fresh one. */
  reset(): void;
}

export interface RunnerOptions {
  baseUrl: string;
  timeoutMs: number;
  firstRunTimeoutMs: number;
  maxOutputChars: number;
}

export function capOutput(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max)}\n[output cut short at ${max} characters]` : text;
}

/** Every test failed because the run stopped (time-out, crash). */
export function allFailed(tests: TestCase[], message: string): TestResult[] {
  return tests.map((t) => ({ name: t.name, passed: false, message }));
}

export class TimeoutError extends Error {
  constructor(seconds: number) {
    super(`Stopped after ${seconds} seconds. Is there an infinite loop?`);
    this.name = "TimeoutError";
  }
}

/** Resolve with the promise, or reject after `ms` (calling `onTimeout`). */
export function withTimeout<T>(promise: Promise<T>, ms: number, onTimeout: () => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      onTimeout();
      reject(new TimeoutError(Math.round(ms / 1000)));
    }, ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        clearTimeout(timer);
        reject(error instanceof Error ? error : new Error(String(error)));
      },
    );
  });
}
