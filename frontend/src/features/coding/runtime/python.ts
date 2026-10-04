import {
  allFailed,
  capOutput,
  TimeoutError,
  withTimeout,
  type RunRequest,
  type RunResult,
  type Runner,
  type RunnerOptions,
  type TestResult,
} from "./types";

interface WorkerResult {
  type: "result";
  id: number;
  output?: string;
  result?: { error: string | null; tests: TestResult[] };
  runtimeMs?: number;
  failure?: string;
}

type WorkerMessage =
  | { type: "ready" }
  | { type: "failed"; error?: string }
  | { type: "started"; id: number }
  | WorkerResult;

interface Pending {
  resolve: (result: WorkerResult) => void;
  started: () => void;
}

/**
 * Python via Pyodide in a Web Worker. Starting Python and downloading
 * packages get the long first-run allowance; only your code's own run is
 * held to the run limit. A run that takes too long cannot be interrupted
 * without cross-origin isolation, so the worker is terminated and the next
 * run starts a fresh one.
 */
export class PythonRunner implements Runner {
  private worker: Worker | null = null;
  private starting: Promise<void> | null = null;
  private nextId = 1;
  private pending = new Map<number, Pending>();

  constructor(
    private readonly options: RunnerOptions,
    private readonly createWorker: () => Worker = () =>
      new Worker(new URL("./python.worker.ts", import.meta.url), { type: "module" }),
  ) {}

  ready(): Promise<void> {
    if (this.starting) return this.starting;
    const worker = this.createWorker();
    this.worker = worker;
    const starting = new Promise<void>((resolve, reject) => {
      worker.onmessage = (event: MessageEvent<WorkerMessage>) => {
        const data = event.data;
        if (data.type === "ready") resolve();
        else if (data.type === "failed") reject(new Error(`Python could not start: ${data.error ?? ""}`));
        else if (data.type === "started") this.pending.get(data.id)?.started();
        else {
          this.pending.get(data.id)?.resolve(data);
          this.pending.delete(data.id);
        }
      };
      worker.onerror = (event) => reject(new Error(event.message || "Python could not start."));
      worker.postMessage({ type: "init", baseUrl: this.options.baseUrl });
    });
    this.starting = withTimeout(starting, this.options.firstRunTimeoutMs, () => this.reset());
    this.starting.catch(() => this.reset());
    return this.starting;
  }

  private send(request: RunRequest): Promise<WorkerResult> {
    return new Promise<WorkerResult>((resolve, reject) => {
      const id = this.nextId++;
      const stop = (ms: number) => () => {
        this.pending.delete(id);
        this.reset();
        reject(new TimeoutError(Math.round(ms / 1000)));
      };
      // Loading packages: the long allowance. Running: the run limit.
      let timer = setTimeout(stop(this.options.firstRunTimeoutMs), this.options.firstRunTimeoutMs);
      this.pending.set(id, {
        resolve: (result) => {
          clearTimeout(timer);
          resolve(result);
        },
        started: () => {
          clearTimeout(timer);
          timer = setTimeout(stop(this.options.timeoutMs), this.options.timeoutMs);
        },
      });
      this.worker?.postMessage({ type: "run", id, ...request });
    });
  }

  async run(request: RunRequest): Promise<RunResult> {
    const started = performance.now();
    try {
      await this.ready();
      const reply = await this.send(request);
      const output = capOutput(reply.output ?? "", this.options.maxOutputChars);
      if (reply.failure || !reply.result) {
        const error = reply.failure ?? "Python stopped unexpectedly.";
        return {
          output,
          error,
          tests: allFailed(request.mode === "test" ? request.tests : [], error),
          runtimeMs: 0,
          timedOut: false,
        };
      }
      return {
        output,
        error: reply.result.error,
        tests: reply.result.tests,
        runtimeMs: reply.runtimeMs ?? 0,
        timedOut: false,
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return {
        output: "",
        error: message,
        tests: allFailed(request.mode === "test" ? request.tests : [], message),
        runtimeMs: Math.round(performance.now() - started),
        timedOut: error instanceof TimeoutError,
      };
    }
  }

  reset(): void {
    this.worker?.terminate();
    this.worker = null;
    this.starting = null;
    for (const pending of this.pending.values()) {
      pending.resolve({ type: "result", id: 0, failure: "Stopped." });
    }
    this.pending.clear();
  }
}
