/**
 * The accessibility pass (Phase 11): axe-core on every main page, signed
 * out and in, plus the command palette, the shortcuts sheet and the phone
 * menu. No violations allowed. Colour contrast needs real layout, so it is
 * checked separately (src/lib/contrast.test.ts, and in a browser).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { routeTree } from "@/app/router";

import { fakeApi, UNAUTHORISED, type Handler } from "./fakeApi";

const m = (value: number | null, basis = "From your answers") => ({ value, basis });
const summary = {
  days: 7, answered: m(20), correct: m(16), accuracy: m(0.8), study_minutes: m(35), reviews: m(12), mistakes: m(2),
};
const module = {
  id: "m1", academic_year_id: "y1", code: "MATH101", title: "Calculus I",
  subject_tag: "Mathematics", credits: 15, colour: null, status: "active",
};
const prefs = {
  session_minutes: 45, max_sessions_per_day: 3, rest_weekdays: [], notify_exams: true, notify_quiz: true,
  notify_neglected: true, notify_flashcards: true, quiz_reminder_hour: 18, quiet_from: null, quiet_to: null,
};
const week = (start: string) => ({
  start, answered: 4, accuracy: 0.6, study_minutes: 30, reviews: 3, sessions_done: 1, sessions_planned: 2, mistakes: { sign_error: 1 },
});
const today = new Date().toISOString().slice(0, 10);

const API: Record<string, Handler> = {
  "GET /api/v1/auth/session": () => [200, { user: { id: "u1", email: "e@example.com", display_name: "Ewan" }, settings: { theme: "system", accent_colour: "#4f46e5" } }],
  "GET /api/v1/years": () => [200, [{ id: "y1", label: "2026/27", start_date: "2026-09-21", end_date: "2027-06-12", is_current: true }]],
  "GET /api/v1/modules": () => [200, [module]],
  "GET /api/v1/modules/m1": () => [200, module],
  "GET /api/v1/modules/m1/topics": () => [200, [{ id: "t1", module_id: "m1", parent_id: null, title: "Series", position: 0, importance: 3, children: [] }]],
  "GET /api/v1/daily-quiz/plan": () => [200, { minutes: 15, seconds_per_question: 90, questions: 10, buckets: [] }],
  "GET /api/v1/flashcards/due": () => [200, { cards: [], counts: { due: 0, review: 0, learning: 0, new: 0 } }],
  "GET /api/v1/progress/weakest": () => [200, []],
  "GET /api/v1/progress": () => [200, []],
  "GET /api/v1/mistakes": () => [200, []],
  "GET /api/v1/plan": () => [200, { generated_at: new Date().toISOString(), starts: today, ends: today, shortfalls: [], today: [], upcoming: [], exams: [] }],
  "GET /api/v1/exams": () => [200, []],
  "GET /api/v1/availability": () => [200, { weekdays: [120, 120, 120, 120, 120, 60, 60], custom: Array(7).fill(false), overrides: [] }],
  "GET /api/v1/planner/preferences": () => [200, prefs],
  "GET /api/v1/calendar": (request) => {
    const url = new URL(request.url);
    const start = url.searchParams.get("start")!;
    return [200, { start, end: url.searchParams.get("end"), days: [{ day: start, available_minutes: 120, sessions: [], exams: [], quizzes: [], reviews: 0, due_cards: 0 }] }];
  },
  "GET /api/v1/analytics/readiness": () => [200, []],
  "GET /api/v1/analytics/trends": () => [200, { weeks: [week("2026-09-28"), week("2026-10-05")], days: [{ day: today, events: 2 }], mistake_labels: { sign_error: "Sign error" }, basis: { accuracy: "a", study_time: "b", mistakes: "c", consistency: "d" } }],
  "GET /api/v1/analytics/overview": () => [200, {
    today: { progress: m(0.5), planned_minutes: 90, done_minutes: 45 }, streak: { current: m(3), longest: m(5) }, recent: summary,
    mastered: m(1), mistake_groups: m(2),
    modules: [{ module_id: "m1", code: "MATH101", title: "Calculus I", colour: null, progress: m(0.6), coverage: m(0.5), mastered: m(1), answered: m(4), accuracy: m(0.7) }],
    strong: [], weak: [], uploads: [], materials: [],
  }],
  "GET /api/v1/analytics/modules/m1": () => [200, { module_id: "m1", progress: m(0.6), coverage: m(0.5), mastered: m(1), recent: summary, readiness: null, recommendation: null }],
  "GET /api/v1/documents": () => [200, []],
  "GET /api/v1/materials": () => [200, []],
  "GET /api/v1/drafts": () => [200, []],
  "GET /api/v1/attempts": () => [200, []],
  "GET /api/v1/ai/budget": () => [200, { currency: "GBP", spent_today: 0, spent_this_month: 0, daily_cap: 2, monthly_cap: 10, warning: false, exhausted: false, configured: true }],
  "GET /api/v1/trash": () => [200, { modules: [], topics: [], documents: [], materials: [], flashcards: [], exercises: [], retention_days: 30 }],
  "GET /api/v1/health/ready": () => [200, { status: "ready", checks: {} }],
  "GET /api/v1/profile": () => [200, { current: { answered: 0, accuracy: null, by_type: {}, exam_conditions: null, untimed: null, recent_errors: { considered: 0, by_category: {} }, hints_per_answer: 0, flashcards: { reviews_30d: 0, recall_rate: null }, recall_minus_application: null, active_days_30d: 0 }, snapshot: null }],
  "GET /api/v1/conversations": () => [200, []],
  "GET /api/v1/coding/exercises": () => [200, []],
  "GET /api/v1/coding/config": () => [200, { runtimes: { python: { label: "Python", base_url: "https://x/" }, r: { label: "R", base_url: "https://y/" } }, run_timeout_seconds: 15, first_run_timeout_seconds: 120, max_output_chars: 20000 }],
};

function renderAt(path: string) {
  const router = createRouter({ routeTree, history: createMemoryHistory({ initialEntries: [path] }) });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

async function violations(): Promise<string[]> {
  const results = await axe.run(document.body, {
    rules: { "color-contrast": { enabled: false } },
    resultTypes: ["violations"],
  });
  return results.violations.flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.target.join(" ")} (${v.help})`));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("accessibility (axe)", () => {
  it("the sign-in page", async () => {
    fakeApi({ "GET /api/v1/auth/session": () => UNAUTHORISED });
    renderAt("/login");
    await screen.findByRole("button", { name: /sign in/i });
    expect(await violations()).toEqual([]);
  });

  for (const [path, heading] of [
    ["/", /Good (morning|afternoon|evening)/],
    ["/planner", "Revision planner"],
    ["/calendar", "Calendar"],
    ["/analytics", "Analytics"],
    ["/settings", "Settings"],
    ["/profile", /Learning profile/],
    ["/mistakes", /Mistake/],
    ["/y/y1/m/m1", "Calculus I"],
    ["/modules/m1/coding", "Coding practice"],
  ] as const) {
    it(`${path}`, async () => {
      fakeApi(API);
      renderAt(path);
      await screen.findByRole("heading", { level: 1, name: heading });
      // Let queries settle so the page is complete.
      await new Promise((r) => setTimeout(r, 50));
      expect(await violations()).toEqual([]);
    });
  }

  it("the command palette and the shortcuts sheet", async () => {
    fakeApi(API);
    const user = userEvent.setup();
    renderAt("/");
    await screen.findByRole("heading", { level: 1 });
    await user.keyboard("{Control>}k{/Control}");
    expect(await screen.findByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
    expect(await violations()).toEqual([]);
    await user.keyboard("{Escape}");
    await user.keyboard("?");
    expect(await screen.findByRole("dialog", { name: "Keyboard shortcuts" })).toBeInTheDocument();
    expect(await violations()).toEqual([]);
  });

  it("the phone layout and its menu", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: false, media: query, addEventListener: () => {}, removeEventListener: () => {},
    }));
    fakeApi(API);
    const user = userEvent.setup();
    renderAt("/");
    await user.click(await screen.findByRole("button", { name: "Open menu" }));
    expect(await screen.findByRole("dialog", { name: "Menu" })).toBeInTheDocument();
    expect(await violations()).toEqual([]);
  });
});

describe("the axe check itself", () => {
  it("does report problems (so a clean result means something)", async () => {
    document.body.innerHTML = '<main><img src="x.png"><button></button></main>';
    const found = await violations();
    expect(found.some((v) => v.startsWith("image-alt"))).toBe(true);
    expect(found.some((v) => v.startsWith("button-name"))).toBe(true);
    document.body.innerHTML = "";
  });
});
