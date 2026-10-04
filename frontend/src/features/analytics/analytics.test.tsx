import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { routeTree } from "@/app/router";
import { fakeApi, type Handler } from "@/test/fakeApi";

import { formatValue } from "./queries";

const session = {
  user: { id: "u1", email: "ewan@example.com", display_name: "Ewan" },
  settings: { theme: "system", accent_colour: "#4f46e5" },
};
const year = { id: "y1", label: "2026/27", start_date: "2026-09-21", end_date: "2027-06-12", is_current: true };
const module = {
  id: "m1", academic_year_id: "y1", code: "MATH101", title: "Calculus I",
  subject_tag: null, credits: 15, colour: null, status: "active",
};
const m = (value: number | null, basis: string) => ({ value, basis });
const recent = {
  days: 7,
  answered: m(20, "Answers marked in the last 7 days"),
  correct: m(16, "Answers marked in the last 7 days with full marks (16 of 20)"),
  accuracy: m(0.8, "Mean mark of 20 answers marked in the last 7 days (partial credit counts)"),
  study_minutes: m(35, "Recorded time of 20 answers and 12 flashcard reviews"),
  reviews: m(12, "Flashcard reviews in the last 7 days"),
  mistakes: m(4, "Answers marked in the last 7 days with a classified mistake: sign error 3"),
};
const readiness = {
  exam_id: "e1", module_id: "m1", module_code: "MATH101", title: "MATH101 final", days_until: 34,
  index: 0.56, band: "Building",
  components: {
    coverage: m(0.5, "1 of 2 exam topics with at least 3 marked answers"),
    strength: m(0.575, "Mean estimated strength of the 2 exam topics"),
    recent: m(0.625, "Mean mark of 4 answers on the exam's topics in the last 14 days"),
    mock: m(null, "No marked mock exams for this module yet"),
    recency: m(0.5, "1 of 2 exam topics practised in the last 7 days"),
  },
  weak_topics: [{ module_id: "m1", module_code: "MATH101", topic_id: "t1", title: "Limits", strength: 0.4, attempts: 1 }],
  note: "A summary of your preparation so far, from the measurements below. It is not a prediction of your mark.",
};
const overview = {
  today: { progress: m(45 / 108, "Today: 1 of 2 planned sessions done (45 of 90 min); daily quiz not done (18 min)"), planned_minutes: 108, done_minutes: 45 },
  streak: { current: m(8, "8 days in a row with at least one answer, flashcard review or completed session"), longest: m(12, "Longest run") },
  recent,
  mastered: m(1, "1 of 4 topics at an estimated 80% or more, with enough data"),
  mistake_groups: m(2, "Mistake-bank groups (by topic and kind of mistake); 1 recurring"),
  modules: [
    {
      module_id: "m1", code: "MATH101", title: "Calculus I", colour: null,
      progress: m(0.72, "Estimated strength of 4 topics with data"),
      coverage: m(0.75, "3 of 4 topics with at least 3 marked answers"),
      mastered: m(1, "1 of 4 topics"),
      answered: m(20, "Answers marked in the last 7 days"),
      accuracy: m(0.8, "Mean mark of 20 answers"),
    },
  ],
  strong: [{ module_id: "m1", module_code: "MATH101", topic_id: "t2", title: "Differentiation", strength: 0.91, attempts: 14 }],
  weak: [{ module_id: "m1", module_code: "MATH101", topic_id: "t1", title: "Integration by Parts", strength: 0.43, attempts: 9 }],
  uploads: [{ id: "d1", filename: "Week 3.pdf", module_code: "MATH101", status: "ready", created_at: "2026-10-04T10:00:00Z" }],
  materials: [{ id: "x1", title: "Series summary", kind: "summary", origin: "claude", module_code: "MATH101", created_at: "2026-10-04T10:00:00Z" }],
};
const week = (start: string, answered: number, accuracy: number | null) => ({
  start, answered, accuracy, study_minutes: answered * 2, reviews: 3, sessions_done: 1, sessions_planned: 2,
  mistakes: answered ? { sign_error: 2 } : {},
});
const trends = {
  weeks: [week("2026-09-21", 0, null), week("2026-09-28", 10, 0.6), week("2026-10-05", 20, 0.8)],
  days: [
    { day: "2026-10-04", events: 3 },
    { day: "2026-10-05", events: 6 },
  ],
  mistake_labels: { sign_error: "Sign error" },
  basis: {
    accuracy: "Mean mark of the answers marked each week, in all your modules",
    study_time: "Recorded time of each week's answers and flashcard reviews",
    mistakes: "Answers with a classified mistake each week, by kind",
    consistency: "Days with at least one answer, flashcard review or completed session",
  },
};
const base: Record<string, Handler> = {
  "GET /api/v1/auth/session": () => [200, session],
  "GET /api/v1/years": () => [200, [year]],
  "GET /api/v1/modules": () => [200, [module]],
  "GET /api/v1/modules/m1": () => [200, module],
  "GET /api/v1/analytics/overview": () => [200, overview],
  "GET /api/v1/analytics/readiness": () => [200, [readiness]],
  "GET /api/v1/analytics/trends": () => [200, trends],
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

describe("formatting", () => {
  it("shows missing data as a dash, never as zero", () => {
    expect(formatValue(null, "percent")).toBe("–");
    expect([formatValue(0.625, "percent"), formatValue(95, "minutes"), formatValue(1, "days")]).toEqual([
      "63%",
      "1 h 35 min",
      "1 day",
    ]);
  });
});

describe("analytics page", () => {
  it("traces every figure to the data behind it", async () => {
    fakeApi(base);
    const user = userEvent.setup();
    renderAt("/analytics");
    await screen.findByRole("heading", { name: "Module performance" });
    await screen.findByRole("region", { name: "Readiness for MATH101 MATH101 final" });

    const explainers = screen.getAllByRole("button", { name: /is worked out/ });
    expect(explainers.length).toBeGreaterThanOrEqual(9);
    for (const button of explainers) {
      const group = button.closest('[role="group"]') as HTMLElement;
      const basis = document.getElementById(button.getAttribute("aria-controls")!)!;
      expect(basis).not.toBeVisible();
      await user.click(button);
      expect(basis).toBeVisible();
      expect(basis.textContent!.length).toBeGreaterThan(10);
      expect(group).toHaveAttribute("title", basis.textContent);
    }
  });

  it("shows readiness as measurements, not a prediction", async () => {
    fakeApi(base);
    renderAt("/analytics");
    const card = await screen.findByRole("region", { name: "Readiness for MATH101 MATH101 final" });
    expect(card).toHaveTextContent("Building");
    expect(card).toHaveTextContent("It is not a prediction of your mark.");
    expect(within(card).getByRole("meter", { name: "Readiness 56 of 100" })).toBeInTheDocument();
    expect(within(card).getByRole("group", { name: "Mock exams" })).toHaveTextContent("–");
    expect(card).toHaveTextContent("Limits (est. 40%)");
  });

  it("draws the trends with their numbers available as text", async () => {
    const { calls } = fakeApi({ ...base });
    const user = userEvent.setup();
    renderAt("/analytics");
    const accuracy = await screen.findByRole("img", { name: "Accuracy by week" });
    expect(accuracy).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Accuracy by week" });
    expect(within(table).getAllByRole("row").map((r) => r.textContent)).toEqual([
      expect.stringMatching(/no data$/),
      expect.stringMatching(/60%$/),
      expect.stringMatching(/80%$/),
    ]);
    expect(screen.getByRole("list", { name: "Mistakes by kind" })).toHaveTextContent("Sign error4");
    expect(screen.getByRole("img", { name: "Revision consistency: active on 2 of 2 days" })).toBeInTheDocument();
    expect(screen.getByText("Mean mark of the answers marked each week, in all your modules")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Show trends for"), "m1");
    await vi.waitFor(() =>
      expect(
        calls.some((c) => c.path === "/api/v1/analytics/trends" && c.method === "GET"),
      ).toBe(true),
    );
  });
});

describe("today at a glance", () => {
  it("shows the day's figures and what was added recently", async () => {
    fakeApi({
      ...base,
      "GET /api/v1/daily-quiz/plan": () => [200, { minutes: 15, seconds_per_question: 90, questions: 0, buckets: [] }],
      "GET /api/v1/flashcards/due": () => [200, { cards: [], counts: { due: 0, review: 0, learning: 0, new: 0 } }],
      "GET /api/v1/progress/weakest": () => [200, []],
      "GET /api/v1/mistakes": () => [200, []],
    });
    const user = userEvent.setup();
    renderAt("/");
    const glance = await screen.findByRole("region", { name: "At a glance" });
    expect(within(glance).getByText("8-day streak")).toBeInTheDocument();
    expect(within(glance).getByRole("group", { name: "Today's progress" })).toHaveTextContent("42%");
    expect(within(glance).getByRole("group", { name: "Study time (7 days)" })).toHaveTextContent("35 min");
    await user.click(within(glance).getByRole("button", { name: "How today's progress is worked out" }));
    expect(within(glance).getByText(/1 of 2 planned sessions done/)).toBeVisible();
    const recentItems = screen.getByRole("region", { name: "Recently added" });
    expect(recentItems).toHaveTextContent("Week 3.pdf");
    expect(recentItems).toHaveTextContent("Series summary");
    expect(recentItems).toHaveTextContent("generated");
  });
});

describe("module overview", () => {
  it("shows the module's figures and starts the recommended practice", async () => {
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/analytics/modules/m1": () => [
        200,
        {
          module_id: "m1",
          progress: overview.modules[0]!.progress,
          coverage: overview.modules[0]!.coverage,
          mastered: overview.modules[0]!.mastered,
          recent,
          readiness,
          recommendation: {
            kind: "topic", title: "Integration by Parts", minutes: 45,
            reason: "est. 43% · 4 mistakes in 30 days · last practised 6 days ago · MATH101 exam in 34 days",
            action: { to: "practice", module_id: "m1", topic_id: "t1", questions: 30 },
          },
        },
      ],
      "GET /api/v1/modules/m1/topics": () => [200, []],
      "GET /api/v1/progress": () => [200, []],
      "GET /api/v1/documents": () => [200, []],
      "GET /api/v1/materials": () => [200, []],
      "GET /api/v1/drafts": () => [200, []],
      "GET /api/v1/attempts": () => [200, []],
      "GET /api/v1/flashcards": () => [200, []],
      "GET /api/v1/questions": () => [200, { items: [], total: 0 }],
      "POST /api/v1/quizzes": () => [201, { quiz: {}, attempt_id: "a1" }],
      "GET /api/v1/attempts/a1": () => [404, { error: { code: "x", message: "x" } }],
    });
    const user = userEvent.setup();
    renderAt("/y/y1/m/m1");
    const overviewRegion = await screen.findByRole("region", { name: "Overview" });
    expect(await within(overviewRegion).findByRole("group", { name: "Correct (7 days)" })).toHaveTextContent("16");
    expect(within(overviewRegion).getByRole("group", { name: "Accuracy (7 days)" })).toHaveTextContent("80%");
    const rec = within(overviewRegion).getByRole("region", { name: "Recommendation" });
    expect(rec).toHaveTextContent("Focus on Integration by Parts next.");
    expect(rec).toHaveTextContent("est. 43% · 4 mistakes in 30 days");
    await user.click(within(rec).getByRole("button", { name: "Practise" }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/quizzes")?.body).toMatchObject({
        module_id: "m1",
        topic_ids: ["t1"],
        count: 30,
      }),
    );
  });
});
