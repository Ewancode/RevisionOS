/**
 * R via the pinned WebR, served from this app's own origin; R packages come
 * from the WebR project's repository. WebR runs R in its own Web
 * Worker; the PostMessage channel avoids needing cross-origin isolation.
 */
import {
  allFailed,
  capOutput,
  TimeoutError,
  withTimeout,
  type RunRequest,
  type RunResult,
  type Runner,
  type RunnerOptions,
  type TestCase,
  type TestResult,
} from "./types";

/** An R raw string holding any text: r"--[...]--", with enough dashes. */
export function rString(text: string): string {
  let dashes = "-";
  while (text.includes(`]${dashes}"`)) dashes += "-";
  return `r"${dashes}[${text}]${dashes}"`;
}

const FAIL = "\u0001";

/**
 * The R side of a test run. Returns a character vector: your code's error
 * (or NA), then one entry per test: "" if it passed, FAIL + message if not.
 * Each test runs in a child of your code's environment, so tests do not
 * leak into each other.
 */
export function testProgram(code: string, tests: TestCase[]): string {
  return `local({
  .code <- ${rString(code)}
  .tests <- c(${tests.map((t) => rString(t.code)).join(", ")})
  .env <- new.env(parent = globalenv())
  .err <- tryCatch({ eval(parse(text = .code), envir = .env); NA_character_ },
    error = function(e) conditionMessage(e))
  .res <- vapply(.tests, function(.t) {
    if (!is.na(.err)) return("${FAIL}Your code raised an error first.")
    tryCatch({ eval(parse(text = .t), envir = new.env(parent = .env)); "" },
      error = function(e) paste0("${FAIL}", conditionMessage(e)))
  }, character(1), USE.NAMES = FALSE)
  c(.err, .res)
})`;
}

export function readResults(values: (string | null)[], tests: TestCase[]): { error: string | null; tests: TestResult[] } {
  const [error = null, ...rest] = values;
  return {
    error,
    tests: tests.map((t, i) => {
      const value = rest[i] ?? `${FAIL}No result.`;
      return { name: t.name, passed: value === "", message: value.startsWith(FAIL) ? value.slice(1) || "Failed." : "" };
    }),
  };
}

interface Capture {
  result: { toArray(): Promise<(string | null)[]> };
  output: { type: string; data: string }[];
}
interface Shelter {
  captureR(code: string, options: Record<string, unknown>): Promise<Capture>;
  purge(): void;
}
interface WebRInstance {
  init(): Promise<void>;
  installPackages(packages: string[], options?: { quiet?: boolean }): Promise<void>;
  close(): void;
  Shelter: new () => Promise<Shelter>;
}
interface WebRModule {
  WebR: new (options: Record<string, unknown>) => WebRInstance;
  ChannelType: { PostMessage: number };
}

export class RRunner implements Runner {
  private webR: Promise<WebRInstance> | null = null;
  private installed = new Set<string>();

  constructor(
    private readonly options: RunnerOptions,
    private readonly loadModule: (url: string) => Promise<WebRModule> = (url) =>
      import(/* @vite-ignore */ url) as Promise<WebRModule>,
  ) {}

  ready(): Promise<void> {
    this.webR ??= (async () => {
      const baseUrl = new URL(this.options.baseUrl, globalThis.location.href).href;
      const { WebR, ChannelType } = await this.loadModule(`${baseUrl}webr.mjs`);
      const webR = new WebR({ baseUrl, repoUrl: this.options.packageUrl, channelType: ChannelType.PostMessage });
      await webR.init();
      return webR;
    })();
    this.webR.catch(() => this.reset());
    return this.webR.then(() => undefined);
  }

  /** Start R and install packages: the long first-run allowance. */
  private async prepare(packages: string[]): Promise<WebRInstance> {
    await this.ready();
    const webR = await this.webR!;
    const wanted = packages.filter((p) => !this.installed.has(p));
    if (wanted.length) {
      await webR.installPackages(wanted, { quiet: true });
      wanted.forEach((p) => this.installed.add(p));
    }
    return webR;
  }

  /** Run your code: the run limit. */
  private async execute(webR: WebRInstance, request: RunRequest): Promise<RunResult> {
    const started = performance.now();
    const shelter = await new webR.Shelter();
    try {
      const code = request.mode === "test" ? testProgram(request.code, request.tests) : request.code;
      let capture: Capture;
      try {
        capture = await shelter.captureR(code, {
          withAutoprint: request.mode === "run",
          captureStreams: true,
          captureConditions: false,
        });
      } catch (error) {
        // A plain run that fails: R's error message.
        return {
          output: "",
          error: error instanceof Error ? error.message : String(error),
          tests: [],
          runtimeMs: Math.round(performance.now() - started),
          timedOut: false,
        };
      }
      const output = capOutput(
        capture.output.filter((o) => o.type === "stdout" || o.type === "stderr").map((o) => o.data).join("\n"),
        this.options.maxOutputChars,
      );
      const runtimeMs = Math.round(performance.now() - started);
      if (request.mode === "run") return { output, error: null, tests: [], runtimeMs, timedOut: false };
      const results = readResults(await capture.result.toArray(), request.tests);
      return { output, ...results, runtimeMs, timedOut: false };
    } finally {
      shelter.purge();
    }
  }

  async run(request: RunRequest): Promise<RunResult> {
    try {
      const webR = await withTimeout(this.prepare(request.packages), this.options.firstRunTimeoutMs, () =>
        this.reset(),
      );
      return await withTimeout(this.execute(webR, request), this.options.timeoutMs, () => this.reset());
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return {
        output: "",
        error: message,
        tests: allFailed(request.mode === "test" ? request.tests : [], message),
        runtimeMs: 0,
        timedOut: error instanceof TimeoutError,
      };
    }
  }

  reset(): void {
    const webR = this.webR;
    this.webR = null;
    this.installed.clear();
    void webR?.then((w) => w.close()).catch(() => undefined);
  }
}
