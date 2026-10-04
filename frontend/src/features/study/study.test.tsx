import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { routeTree } from "@/app/router";
import { fakeApi } from "@/test/fakeApi";

const session = {
  user: { id: "u1", email: "ewan@example.com", display_name: "Ewan" },
  settings: { theme: "system", accent_colour: "#4f46e5" },
};
const year = { id: "y1", label: "2026/27", start_date: "2026-09-21", end_date: "2027-06-12", is_current: true };
const module = {
  id: "m1",
  academic_year_id: "y1",
  code: "MATH101",
  title: "Calculus I",
  subject_tag: null,
  credits: 15,
  colour: null,
  status: "active",
};
const base = {
  "GET /api/v1/auth/session": () => [200, session] as [number, unknown],
  "GET /api/v1/years": () => [200, [year]] as [number, unknown],
  "GET /api/v1/modules": () => [200, [module]] as [number, unknown],
  "GET /api/v1/modules/m1": () => [200, module] as [number, unknown],
  "GET /api/v1/modules/m1/topics": () => [200, []] as [number, unknown],
  "GET /api/v1/documents": () => [200, []] as [number, unknown],
};

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

const NULLS = {
  options: null,
  correct_option: null,
  true_or_false: null,
  value: null,
  unit: null,
  expression: null,
  accepted_answers: null,
  rubric: null,
  model_answer: null,
};
const draft = {
  id: "d1",
  module_id: "m1",
  topic_id: null,
  kind: "questions",
  request: { count: 2 },
  status: "ready",
  error_code: null,
  created_at: "2026-10-02T10:00:00Z",
  updated_at: "2026-10-02T10:00:00Z",
  payload: {
    passages: [{ n: 1, document_id: "doc1", filename: "Week 1.pdf", page_no: 4, source_tier: "university" }],
    items: [
      {
        ...NULLS,
        type: "multiple_choice",
        difficulty: "easy",
        stem_md: "Is $e^{i\\pi} = -1$?",
        solution_md: "Euler.",
        options: ["Yes", "No"],
        correct_option: 0,
        sources: [1],
        problems: [],
        valid: true,
      },
      {
        ...NULLS,
        type: "numerical",
        difficulty: "medium",
        stem_md: "Integrate.",
        solution_md: "9",
        value: 10,
        sources: [1],
        problems: ["the answer 10 does not match its check (9)"],
        valid: false,
      },
    ],
  },
};

describe("drafts", () => {
  it("shows which generated items passed the checks and saves only those", async () => {
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/drafts/d1": () => [200, draft],
      "POST /api/v1/drafts/d1/save": () => [200, { draft: { ...draft, status: "saved" }, saved_items: 1 }],
      "GET /api/v1/questions": () => [200, []],
      "GET /api/v1/attempts": () => [200, []],
    });
    const user = userEvent.setup();
    const router = renderAt("/drafts/d1");

    expect(await screen.findByText(/1 of 2 questions passed/)).toBeInTheDocument();
    const boxes = screen.getAllByRole("checkbox", { name: /Keep item/ });
    expect(boxes[0]).toBeChecked();
    expect(boxes[1]).toBeDisabled();
    expect(screen.getByRole("note")).toHaveTextContent("does not match its check");
    const [source] = screen.getAllByRole("link", { name: "Week 1.pdf p.4" });
    expect(source).toHaveAttribute("href", "/doc/doc1?page=4");

    await user.click(screen.getByRole("button", { name: /Save 1 question/ }));
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/modules/m1/questions"));
    expect(calls.find((c) => c.path === "/api/v1/drafts/d1/save")?.body).toEqual({ selected: [0] });
  });

  it("previews a generated material with its citations", async () => {
    fakeApi({
      ...base,
      "GET /api/v1/drafts/d2": () => [
        200,
        {
          ...draft,
          id: "d2",
          kind: "material",
          payload: {
            title: "Series — Revision Guide",
            content_md: "# Series — Revision Guide\n\nThe ratio test. [[1]](#cite-1)",
            citations: [
              {
                n: 1,
                document_id: "doc1",
                filename: "Week 1.pdf",
                page_no: 9,
                source_tier: "university",
                module_code: "MATH101",
                heading_path: "",
                quote: "ratio",
              },
            ],
          },
        },
      ],
    });
    renderAt("/drafts/d2");
    expect(await screen.findByRole("link", { name: "Source 1: Week 1.pdf — page 9" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("Series — Revision Guide");
  });

  it("asks Claude for a draft from the generate dialog", async () => {
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/questions": () => [200, []],
      "GET /api/v1/attempts": () => [200, []],
      "POST /api/v1/drafts": () => [202, { ...draft, id: "d9", status: "generating", payload: null }],
      "GET /api/v1/drafts/d9": () => [200, { ...draft, id: "d9", status: "generating", payload: null }],
    });
    const user = userEvent.setup();
    const router = renderAt("/modules/m1/questions");
    await user.click(await screen.findByRole("button", { name: /Generate questions/ }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("checkbox", { name: "Derivation or proof" }));
    await user.type(within(dialog).getByRole("textbox"), "the ratio test");
    await user.click(within(dialog).getByRole("button", { name: "Generate" }));

    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/drafts/d9"));
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
      module_id: "m1",
      kind: "questions",
      count: 8,
      types: ["derivation"],
      instructions: "the ratio test",
    });
    expect(await screen.findByText(/Claude is writing this/)).toBeInTheDocument();
  });
});

const attempt = {
  id: "a1",
  quiz: { id: "q1", module_id: "m1", kind: "mock", title: "MATH101 mock exam", time_limit_minutes: 60, created_at: "" },
  mode: "exam",
  status: "in_progress",
  started_at: "2026-10-02T10:00:00Z",
  deadline: new Date(Date.now() + 30 * 60_000).toISOString(),
  submitted_at: null,
  summary: null,
  items: [
    {
      position: 0,
      question_id: "qa",
      type: "multiple_choice",
      difficulty: "easy",
      topic_id: null,
      stem_md: "Which converges?",
      view: { options: ["$\\sum 1/n$", "$\\sum 1/n^2$"] },
      response: null,
      time_ms: null,
      self_confidence: null,
      has_photo: false,
    },
    {
      position: 1,
      question_id: "qb",
      type: "derivation",
      difficulty: "exam",
      topic_id: null,
      stem_md: "Prove it.",
      view: { marks: 3 },
      response: null,
      time_ms: null,
      self_confidence: null,
      has_photo: false,
    },
  ],
};

describe("quizzes", () => {
  it("answers, saves and submits a timed exam", async () => {
    const marked = {
      ...attempt,
      status: "marked",
      submitted_at: "2026-10-02T10:20:00Z",
      summary: {
        questions: 2,
        answered: 2,
        correct: 1,
        partial: 1,
        incorrect: 0,
        unmarked: 0,
        score: 0.67,
        time_taken_seconds: 1200,
        by_difficulty: [],
        by_topic: [],
        weak_areas: [],
        next_steps: ["Retry the 1 question you got wrong."],
      },
      items: [
        { ...attempt.items[0], response: { choice: 1 }, question_attempt_id: "x1", score: 1, marked_by: "rule", correct_answer: "2. $\\sum 1/n^2$", solution_md: "p-series", feedback: null },
        {
          ...attempt.items[1],
          response: { text: "Because." },
          question_attempt_id: "x2",
          score: 1 / 3,
          marked_by: "ai",
          marking_confidence: "high",
          correct_answer: "proof",
          solution_md: "Full proof.",
          feedback: {
            summary: "Incomplete.",
            points: [{ point: "Uses comparison", marks: 1, awarded: 1, comment: "good" }],
            explanation: {
              why_wrong: "Missed the bound.",
              correct_answer: "Bound by 1/n^2.",
              reasoning: "Compare.",
              mistake: "Stopped early",
              how_to_avoid: "Finish the argument.",
            },
          },
        },
      ],
    };
    let current: unknown = attempt;
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/attempts/a1": () => [200, current],
      "PUT /api/v1/attempts/a1/responses/qa": () => [204, null],
      "PUT /api/v1/attempts/a1/responses/qb": () => [204, null],
      "POST /api/v1/attempts/a1/submit": () => {
        current = marked;
        return [200, marked];
      },
      "POST /api/v1/answers/x2/dispute": () => [200, marked],
    });
    const user = userEvent.setup();
    renderAt("/attempts/a1");

    expect(await screen.findByRole("timer")).toHaveTextContent(/^\s*\d+:\d\d/);
    expect(screen.getByText(/AI help is off/)).toBeInTheDocument();
    const [first] = screen.getAllByRole("radio");
    await user.click(screen.getAllByRole("radio")[1] ?? first!);
    await user.type(screen.getByRole("textbox", { name: "Your answer" }), "Because.");
    await user.click(screen.getByRole("button", { name: "Submit quiz" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Submit" }));

    expect(await screen.findByText("Missed the bound.")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/v1/attempts/a1/responses/qa")?.body).toMatchObject({
      response: { choice: 1 },
    });
    expect(calls.find((c) => c.path === "/api/v1/attempts/a1/responses/qb")?.body).toMatchObject({
      response: { text: "Because." },
    });
    expect(screen.getByText("Retry the 1 question you got wrong.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Dispute mark/ }));
    expect(calls.some((c) => c.path === "/api/v1/answers/x2/dispute")).toBe(true);
  });
});

describe("materials", () => {
  it("compares an old version with the current one", async () => {
    const material = {
      id: "mat1",
      module_id: "m1",
      topic_id: null,
      title: "Series guide",
      kind: "guide",
      origin: "claude",
      created_at: "2026-10-01T10:00:00Z",
      updated_at: "2026-10-02T10:00:00Z",
      current: {
        id: "v2",
        version_no: 2,
        created_by: "user",
        change_note: "Rewrote",
        created_at: "2026-10-02T10:00:00Z",
        content_md: "New text",
        citations: [],
      },
      versions: [
        { id: "v2", version_no: 2, created_by: "user", change_note: "Rewrote", created_at: "2026-10-02T10:00:00Z" },
        { id: "v1", version_no: 1, created_by: "claude", change_note: null, created_at: "2026-10-01T10:00:00Z" },
      ],
    };
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/materials/mat1": () => [200, material],
      "GET /api/v1/materials/mat1/diff": () => [
        200,
        { from_version: 1, to_version: 2, lines: [{ op: "delete", text: "Old text" }, { op: "insert", text: "New text" }] },
      ],
      "POST /api/v1/materials/mat1/versions/v1/restore": () => [200, material],
    });
    const user = userEvent.setup();
    renderAt("/materials/mat1");

    const history = await screen.findByRole("complementary", { name: "Version history" });
    await user.click(within(history).getByRole("button", { name: /Compare/ }));
    const changes = await screen.findByRole("region", { name: "Changes" });
    expect(changes).toHaveTextContent("Removed: Old text");
    expect(changes).toHaveTextContent("Added: New text");
    await user.click(within(history).getByRole("button", { name: /Restore/ }));
    expect(calls.some((c) => c.path === "/api/v1/materials/mat1/versions/v1/restore")).toBe(true);
  });
});

describe("flashcards", () => {
  it("reveals the answer when studying", async () => {
    fakeApi({
      ...base,
      "GET /api/v1/flashcards": () => [
        200,
        [
          {
            id: "c1",
            module_id: "m1",
            topic_id: null,
            front_md: "State the ratio test.",
            back_md: "If $L < 1$ it converges.",
            origin: "claude",
            sources: [],
            created_at: "",
            fsrs_state: 1,
            due: "",
            last_review: null,
            reps: 0,
            lapses: 0,
          },
        ],
      ],
    });
    const user = userEvent.setup();
    renderAt("/modules/m1/flashcards");
    await user.click(await screen.findByRole("button", { name: "Browse 1 cards" }));
    const study = screen.getByRole("region", { name: "Study flashcards" });
    expect(within(study).queryByText(/it converges/)).toBeNull();
    await user.click(within(study).getByRole("button", { name: "Reveal answer" }));
    expect(within(study).getByText(/it converges/)).toBeInTheDocument();
  });
});
