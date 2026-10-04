import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { routeTree } from "@/app/router";
import { fakeApi, type Handler } from "@/test/fakeApi";

import { setRunnerForTests } from "./runtime";
import { PythonRunner } from "./runtime/python";
import { readResults, rString, testProgram } from "./runtime/r";
import type { RunRequest, RunResult, Runner } from "./runtime/types";

const PY_URL = "https://cdn.example/pyodide/";
const R_URL = "https://cdn.example/webr/";
const session = {
  user: { id: "u1", email: "ewan@example.com", display_name: "Ewan" },
  settings: { theme: "system", accent_colour: "#4f46e5" },
};
const year = { id: "y1", label: "2026/27", start_date: "2026-09-21", end_date: "2027-06-12", is_current: true };
const module = {
  id: "m1", academic_year_id: "y1", code: "MATH163", title: "Statistics with R",
  subject_tag: null, credits: 15, colour: null, status: "active",
};
const config = {
  runtimes: { python: { label: "Python", base_url: PY_URL }, r: { label: "R", base_url: R_URL } },
  run_timeout_seconds: 15, first_run_timeout_seconds: 120, max_output_chars: 20000,
};
const exercise = {
  id: "x1", module_id: "m1", topic_id: null, language: "python", title: "Median of a list",
  difficulty: "easy", origin: "claude", assessed: false, created_at: "2026-10-04T10:00:00Z",
  progress: { submissions: 0, best_passed: null, total: 2, solved: false },
  prompt_md: "Write `median(xs)`.", starter_code: "def median(xs):\n    pass\n",
  tests: [
    { name: "odd list", code: "assert median([3, 1, 2]) == 2", hidden: false },
    { name: "single item", code: "assert median([7]) == 7, 'median([7]) should be 7'", hidden: true },
  ],
  packages: [], sources: [], latest_code: null,
};
const noHints = { hints: [], next_level: 1, next_label: "Guiding question", top: 4, locked_reason: "The full solution unlocks after you submit an attempt." };
const base: Record<string, Handler> = {
  "GET /api/v1/auth/session": () => [200, session],
  "GET /api/v1/years": () => [200, [year]],
  "GET /api/v1/modules": () => [200, [module]],
  "GET /api/v1/modules/m1": () => [200, module],
  "GET /api/v1/coding/config": () => [200, config],
};

/** A runner that answers from a script, recording what it was asked. */
class FakeRunner implements Runner {
  requests: RunRequest[] = [];
  constructor(private readonly answer: (r: RunRequest) => RunResult) {}
  ready() {
    return Promise.resolve();
  }
  run(request: RunRequest) {
    this.requests.push(request);
    return Promise.resolve(this.answer(request));
  }
  reset() {}
}

function result(tests: [string, boolean, string?][], extra: Partial<RunResult> = {}): RunResult {
  return {
    output: "",
    error: null,
    tests: tests.map(([name, passed, message]) => ({ name, passed, message: message ?? "" })),
    runtimeMs: 12,
    timedOut: false,
    ...extra,
  };
}

function renderAt(path: string) {
  const router = createRouter({ routeTree, history: createMemoryHistory({ initialEntries: [path] }) });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

afterEach(() => {
  setRunnerForTests("python", PY_URL, null);
  setRunnerForTests("r", R_URL, null);
});

describe("an exercise", () => {
  it("runs the tests in the browser, hides hidden tests, and submits the results", async () => {
    const runner = new FakeRunner(() =>
      result([["odd list", true], ["single item", false, "median([7]) should be 7"]], { output: "hello" }),
    );
    setRunnerForTests("python", PY_URL, runner);
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/coding/exercises/x1": () => [200, exercise],
      "GET /api/v1/coding/exercises/x1/submissions": () => [200, []],
      "GET /api/v1/coding/exercises/x1/hints": () => [200, noHints],
      "POST /api/v1/coding/exercises/x1/submissions": (_r, body) => [
        201,
        { id: "s1", ...(body as object), passed: 1, total: 2, runtime_ms: 12, created_at: "2026-10-04T10:00:00Z" },
      ],
    });
    const user = userEvent.setup();
    renderAt("/coding/x1");

    expect(await screen.findByRole("heading", { name: "Median of a list" })).toBeInTheDocument();
    const visible = screen.getByRole("region", { name: "Visible tests" });
    expect(visible).toHaveTextContent("assert median([3, 1, 2]) == 2");
    expect(visible).not.toHaveTextContent("median([7])");

    await user.click(screen.getByRole("button", { name: /Run tests/ }));
    const results = await screen.findByRole("region", { name: "Results" });
    expect(within(results).getByRole("status")).toHaveTextContent("1 of 2 tests passed");
    const tests = within(results).getByRole("list", { name: "Tests" });
    expect(tests).toHaveTextContent("Hidden test 1");
    expect(tests).not.toHaveTextContent("median([7]) should be 7");
    expect(within(results).getByLabelText("Output")).toHaveTextContent("hello");
    expect(runner.requests[0]).toMatchObject({ mode: "test", code: exercise.starter_code });
    expect(runner.requests[0]!.tests).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: /Submit/ }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.path.endsWith("/submissions"))?.body).toEqual({
        code: exercise.starter_code,
        results: [
          { name: "odd list", passed: true, message: "" },
          { name: "single item", passed: false, message: "median([7]) should be 7" },
        ],
        error: null,
        runtime_ms: 12,
      }),
    );
    expect(await screen.findByText(/Submitted: 1 of 2 tests passed/)).toBeInTheDocument();
  });

  it("asks the tutor for one rung at a time, sending the code and visible results", async () => {
    setRunnerForTests("python", PY_URL, new FakeRunner(() => result([["odd list", false, "AssertionError"], ["single item", false, "x"]])));
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/coding/exercises/x1": () => [200, exercise],
      "GET /api/v1/coding/exercises/x1/submissions": () => [200, []],
      "GET /api/v1/coding/exercises/x1/hints": () => [200, noHints],
      "POST /api/v1/coding/exercises/x1/hints": () => [
        200,
        {
          hints: [{ level: 1, label: "Guiding question", content_md: "What is in the middle once the list is **sorted**?", created_at: "" }],
          next_level: 2, next_label: "Hint", top: 4,
          locked_reason: "The full solution unlocks after you submit an attempt.",
        },
      ],
    });
    const user = userEvent.setup();
    renderAt("/coding/x1");
    await user.click(await screen.findByRole("button", { name: /Run tests/ }));
    await screen.findByRole("region", { name: "Results" });
    await user.click(screen.getByRole("button", { name: "Stuck? Guiding question" }));
    const hints = await screen.findByRole("region", { name: "Hints" });
    expect(await within(hints).findByText(/once the list is/)).toBeInTheDocument();
    expect(within(hints).getByRole("button", { name: "Next: Hint" })).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST" && c.path.endsWith("/hints"))?.body).toEqual({
      work: exercise.starter_code,
      // Hidden tests are left out of what the tutor sees.
      results: "odd list: failed (AssertionError)",
    });
  });
});

describe("Claude's exercises in a draft", () => {
  it("runs each reference solution in the browser and saves only those that pass", async () => {
    const item = (title: string) => ({
      title, language: "python", difficulty: "easy", prompt_md: "Do it.", starter_code: "pass",
      solution_code: `# ${title}`, tests: [{ name: "t", code: "assert True", hidden: false }],
      packages: [], sources: [], problems: [], valid: true,
    });
    const runner = new FakeRunner((r) =>
      r.code.includes("Good") ? result([["t", true]]) : result([["t", false, "AssertionError: wrong"]]),
    );
    setRunnerForTests("python", PY_URL, runner);
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/drafts/d1": () => [
        200,
        {
          id: "d1", module_id: "m1", topic_id: null, kind: "coding", request: {}, status: "ready",
          payload: { items: [item("Good"), item("Wrong")], passages: [] }, error_code: null,
          created_at: "", updated_at: "",
        },
      ],
      "POST /api/v1/drafts/d1/save": () => [200, { draft: {}, material_id: null, saved_items: 1 }],
      "GET /api/v1/coding/exercises": () => [200, []],
    });
    const user = userEvent.setup();
    const router = renderAt("/drafts/d1");
    const save = await screen.findByRole("button", { name: /Save 0 exercises/ });
    expect(save).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /Check the solutions in your browser/ }));
    expect(await screen.findByText(/passes all 1 tests in your browser/)).toBeInTheDocument();
    expect(screen.getByText(/fails its own tests, so it cannot be saved/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Keep exercise 2" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /Save 1 exercise/ }));
    await vi.waitFor(() => expect(calls.find((c) => c.path === "/api/v1/drafts/d1/save")?.body).toEqual({ selected: [0] }));
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/modules/m1/coding"));
  });
});

describe("hints during a practice quiz", () => {
  const attempt = (mode: "normal" | "exam") => ({
    id: "a1", mode, status: "in_progress", deadline: null, started_at: "", submitted_at: null,
    quiz: { id: "q", title: "Quiz", kind: "practice", module_id: "m1", time_limit_minutes: null, created_at: "" },
    items: [
      {
        position: 0, question_id: "qq", type: "multiple_choice", difficulty: "easy", topic_id: null,
        stem_md: "Which is the ratio test?", view: { options: ["A", "B"] }, response: { choice: 1 },
        time_ms: null, self_confidence: null, has_photo: false,
      },
    ],
  });

  it("gives the ladder in a practice quiz, sending your answer so far", async () => {
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/attempts/a1": () => [200, attempt("normal")],
      "GET /api/v1/attempts/a1/responses/qq/hints": () => [200, noHints],
      "POST /api/v1/attempts/a1/responses/qq/hints": () => [
        200,
        { hints: [{ level: 1, label: "Guiding question", content_md: "What does the limit compare?", created_at: "" }], next_level: 2, next_label: "Hint", top: 4, locked_reason: "The worked solution appears when you submit the quiz." },
      ],
    });
    const user = userEvent.setup();
    renderAt("/attempts/a1");
    await user.click(await screen.findByRole("button", { name: /Stuck\? Get a hint/ }));
    await user.click(await screen.findByRole("button", { name: "Stuck? Guiding question" }));
    expect(await screen.findByText("What does the limit compare?")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST" && c.path.endsWith("/hints"))?.body).toEqual({ work: "Chose: B" });
  });

  it("offers no hints under exam conditions", async () => {
    fakeApi({ ...base, "GET /api/v1/attempts/a1": () => [200, attempt("exam")] });
    renderAt("/attempts/a1");
    expect(await screen.findByText("Which is the ratio test?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Get a hint/ })).toBeNull();
  });
});

describe("the R test program", () => {
  it("quotes any code safely as an R raw string", () => {
    expect(rString('x <- "a"')).toBe('r"-[x <- "a"]-"');
    expect(rString('s <- r"-[a]-"')).toBe('r"--[s <- r"-[a]-"]--"');
  });

  it("runs each test in its own environment and reads the results back", () => {
    const program = testProgram("f <- function(x) x", [{ name: "a", code: "stopifnot(f(1) == 1)" }]);
    expect(program).toContain('.code <- r"-[f <- function(x) x]-"');
    expect(program).toContain("new.env(parent = .env)");
    const tests = [
      { name: "a", code: "" },
      { name: "b", code: "" },
    ];
    expect(readResults([null, "", "\u0001f(2) should be 4"], tests)).toEqual({
      error: null,
      tests: [
        { name: "a", passed: true, message: "" },
        { name: "b", passed: false, message: "f(2) should be 4" },
      ],
    });
    expect(readResults(["object 'y' not found", "\u0001Your code raised an error first."], tests.slice(0, 1)).error).toBe(
      "object 'y' not found",
    );
  });
});

describe("the Python runner", () => {
  it("gives package downloads the long allowance, then stops runaway code and restarts", async () => {
    vi.useFakeTimers();
    try {
      const workers: FakeWorker[] = [];
      const runner = new PythonRunner(
        { baseUrl: PY_URL, timeoutMs: 1000, firstRunTimeoutMs: 60_000, maxOutputChars: 100 },
        () => {
          const w = new FakeWorker();
          workers.push(w);
          return w as unknown as Worker;
        },
      );
      const pending = runner.run({ code: "while True: pass", tests: [], mode: "run", packages: ["pandas"] });
      await vi.advanceTimersByTimeAsync(0);
      workers[0]!.reply({ type: "ready" });
      await vi.advanceTimersByTimeAsync(30_000); // still downloading: not stopped
      const run = workers[0]!.sent.find((m) => m.type === "run")!;
      workers[0]!.reply({ type: "started", id: run.id });
      await vi.advanceTimersByTimeAsync(1000);
      const outcome = await pending;
      expect(outcome.timedOut).toBe(true);
      expect(outcome.error).toBe("Stopped after 1 seconds. Is there an infinite loop?");
      expect(workers[0]!.terminated).toBe(true);
      // The next run starts a fresh worker.
      void runner.run({ code: "print(1)", tests: [], mode: "run", packages: [] });
      await vi.advanceTimersByTimeAsync(0);
      expect(workers).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });
});

class FakeWorker {
  sent: { type: string; id?: number }[] = [];
  terminated = false;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: ErrorEvent) => void) | null = null;
  postMessage(message: { type: string; id?: number }) {
    this.sent.push(message);
  }
  reply(data: unknown) {
    this.onmessage?.({ data } as MessageEvent);
  }
  terminate() {
    this.terminated = true;
  }
}
