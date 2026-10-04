import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { routeTree } from "@/app/router";
import { fakeApi } from "@/test/fakeApi";

import { evidence, formatInterval } from "./queries";

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
};
const card = {
  id: "c1",
  module_id: "m1",
  topic_id: null,
  front_md: "State the ratio test.",
  back_md: "If $L < 1$ the series converges.",
  origin: "claude",
  sources: [],
  created_at: "",
  fsrs_state: 1,
  due: "2026-10-05T09:00:00Z",
  last_review: null,
  reps: 0,
  lapses: 0,
  intervals: { 1: 1 / 1440, 2: 6 / 1440, 3: 10 / 1440, 4: 8 },
};
const plan = {
  minutes: 15,
  seconds_per_question: 90,
  questions: 10,
  buckets: [
    {
      module_id: "m1",
      module_code: "MATH101",
      topic_id: "t1",
      title: "Series",
      strength: 0.42,
      attempts: 9,
      low_data: false,
      priority: 1.4,
      terms: { weakness: 0.58, overdue: 0.3, urgency: 0, recurring: 1, gap: 0 },
      available: 12,
      allocated: 6,
      reasons: ["est. 42% strength", "recurring sign error"],
    },
  ],
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

describe("evidence text", () => {
  it("reads like the design: estimate, attempts, recency, data", () => {
    const ago = new Date(Date.now() - 6 * 86_400_000).toISOString();
    expect(evidence({ strength: 0.72, attempts: 14, low_data: false, last_practised_at: ago })).toBe(
      "est. 72% · 14 attempts · last practised 6 days ago",
    );
    expect(evidence({ strength: 0.5, attempts: 1, low_data: true, last_practised_at: null })).toBe(
      "est. 50% · 1 attempt · not practised yet · low data",
    );
    expect([formatInterval(1 / 1440), formatInterval(0.5), formatInterval(11), formatInterval(46)]).toEqual([
      "1 min",
      "12 h",
      "11 d",
      "2 mo",
    ]);
  });
});

describe("flashcard review", () => {
  it("reveals, shows each rating's interval and records the rating", async () => {
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/flashcards/due": () => [200, { cards: [card], counts: { due: 1, review: 0, learning: 0, new: 1 } }],
      "POST /api/v1/flashcards/c1/review": () => [200, { ...card, reps: 1, fsrs_state: 2 }],
    });
    const user = userEvent.setup();
    renderAt("/review");

    const session_ = await screen.findByRole("region", { name: "Flashcard review" });
    expect(within(session_).queryByText(/converges/)).toBeNull();
    await user.keyboard(" ");
    expect(within(session_).getByText(/converges/)).toBeInTheDocument();
    const ratings = within(session_).getByRole("group", { name: "How well did you know it?" });
    expect(within(ratings).getByRole("button", { name: /Easy\s*8 d/ })).toBeInTheDocument();

    await user.keyboard("3");
    await vi.waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/flashcards/c1/review")?.body).toMatchObject({ rating: 3 }),
    );
    expect(await screen.findByText(/Done: 1 review/)).toBeInTheDocument();
  });
});

describe("today", () => {
  it("explains the daily quiz and starts it", async () => {
    fakeApi({
      ...base,
      "GET /api/v1/daily-quiz/plan": () => [200, plan],
      "GET /api/v1/flashcards/due": () => [200, { cards: [], counts: { due: 0, review: 0, learning: 0, new: 0 } }],
      "GET /api/v1/progress/weakest": () => [
        200,
        [{ module_id: "m1", module_code: "MATH101", topic_id: "t1", title: "Series", strength: 0.42, attempts: 9, low_data: false, last_practised_at: null }],
      ],
      "GET /api/v1/mistakes": () => [
        200,
        [
          {
            module_id: "m1", module_code: "MATH101", topic_id: "t1", topic_title: "Series",
            category: "sign_error", label: "Sign error", count: 4, recent: 3, recurring: true,
            last_at: null, patterns: [], examples: [],
          },
        ],
      ],
      "POST /api/v1/daily-quiz": () => [200, { attempt_id: "a1", plan }],
      "GET /api/v1/attempts/a1": () => [404, { error: { code: "x", message: "x" } }],
    });
    const user = userEvent.setup();
    const router = renderAt("/");

    const daily = await screen.findByRole("region", { name: "Daily quiz" });
    expect(await within(daily).findByText(/10 questions, about 15 minutes/)).toBeInTheDocument();
    expect(within(daily).getByText(/recurring sign error/)).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Estimated strength 42%" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Recurring mistakes" })).toHaveTextContent("Sign error");
    await user.click(within(daily).getByRole("button", { name: /Start/ }));
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/attempts/a1"));
  });
});

describe("mistake bank", () => {
  it("retries the questions behind a recurring mistake", async () => {
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/mistakes": () => [
        200,
        [
          {
            module_id: "m1", module_code: "MATH101", topic_id: "t1", topic_title: "Integration",
            category: "sign_error", label: "Sign error", count: 3, recent: 3, recurring: true,
            last_at: "2026-10-05T09:00:00Z",
            patterns: [{ description: "Dropped the minus sign", count: 3 }],
            examples: [
              { answer_id: "x1", attempt_id: "a0", question_id: "q1", stem_md: "Integrate", at: "2026-10-05T09:00:00Z", description: "d" },
              { answer_id: "x2", attempt_id: "a0", question_id: "q2", stem_md: "Integrate", at: "2026-10-05T09:00:00Z", description: "d" },
            ],
          },
        ],
      ],
      "POST /api/v1/quizzes": () => [201, { quiz: {}, attempt_id: "a2" }],
      "GET /api/v1/attempts/a2": () => [404, { error: { code: "x", message: "x" } }],
    });
    const user = userEvent.setup();
    renderAt("/mistakes?module_id=m1");

    expect(await screen.findByText("Recurring")).toBeInTheDocument();
    expect(screen.getByText("×3")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Retry these/ }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/quizzes")?.body).toMatchObject({
        module_id: "m1",
        question_ids: ["q1", "q2"],
      }),
    );
  });
});

describe("learning profile", () => {
  it("shows the weekly summary and the measurements behind it", async () => {
    fakeApi({
      ...base,
      "GET /api/v1/profile": () => [
        200,
        {
          current: {
            answered: 24, accuracy: 0.62,
            by_type: { multiple_choice: { answered: 14, accuracy: 0.79 }, derivation: { answered: 10, accuracy: 0.4 } },
            exam_conditions: { answered: 8, accuracy: 0.5 }, untimed: { answered: 16, accuracy: 0.69 },
            recent_errors: { considered: 9, by_category: { sign_error: 4, notation: 2 } },
            hints_per_answer: 0, flashcards: { reviews_30d: 30, recall_rate: 0.85 },
            recall_minus_application: 0.23, active_days_30d: 6,
          },
          snapshot: { week_start: "2026-10-05", metrics: {}, summary_md: "- Sign errors were 4 of your last 9 mistakes.", computed_at: "" },
        },
      ],
    });
    renderAt("/profile");
    expect(await screen.findByText(/Sign errors were 4 of your last 9 mistakes/)).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Derivation or proof" })).toBeInTheDocument();
    expect(screen.getByText(/you know the facts better than you apply them/)).toBeInTheDocument();
  });
});
