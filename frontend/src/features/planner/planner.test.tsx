import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { routeTree } from "@/app/router";
import { fakeApi, type Handler } from "@/test/fakeApi";

import { addDays, isoDay, weekStart } from "./queries";

const session = {
  user: { id: "u1", email: "ewan@example.com", display_name: "Ewan" },
  settings: { theme: "system", accent_colour: "#4f46e5" },
};
const year = { id: "y1", label: "2026/27", start_date: "2026-09-21", end_date: "2027-06-12", is_current: true };
const module = {
  id: "m1", academic_year_id: "y1", code: "MATH101", title: "Calculus I",
  subject_tag: null, credits: 15, colour: null, status: "active",
};
const empty = { cards: [], counts: { due: 0, review: 0, learning: 0, new: 0 } };
const base: Record<string, Handler> = {
  "GET /api/v1/auth/session": () => [200, session],
  "GET /api/v1/years": () => [200, [year]],
  "GET /api/v1/modules": () => [200, [module]],
  "GET /api/v1/modules/m1": () => [200, module],
  "GET /api/v1/daily-quiz/plan": () => [200, { minutes: 15, seconds_per_question: 90, questions: 0, buckets: [] }],
  "GET /api/v1/flashcards/due": () => [200, empty],
  "GET /api/v1/progress/weakest": () => [200, []],
  "GET /api/v1/mistakes": () => [200, []],
};

const today = isoDay(new Date());
const exam = {
  id: "e1", module_id: "m1", module_code: "MATH101", title: "MATH101 final",
  starts_at: new Date(Date.now() + 34 * 86_400_000).toISOString(), duration_minutes: 120,
  location: null, weighting: 60, confidence: 2, notes: null, topic_ids: [], days_until: 34,
};
const studySession = {
  id: "s1", module_id: "m1", module_code: "MATH101", topic_id: "t3", title: "Integration",
  exam_id: "e1", kind: "topic", day: today, minutes: 45, status: "planned", locked: false,
  actual_minutes: null,
  reason: "est. 30% · 4 mistakes in 30 days · last practised 6 days ago · MATH101 exam in 34 days",
};
const plan = {
  generated_at: new Date().toISOString(), starts: today, ends: addDays(today, 34),
  shortfalls: [], today: [studySession], upcoming: [], exams: [exam],
};
const built = {
  minutes: 45,
  summary: "45 minutes: Review 12 due flashcards (15 min); Drill sign errors (10 min); Practise Integration (20 min).",
  blocks: [
    { kind: "flashcards", title: "Review 12 due flashcards", minutes: 15, reason: "12 cards due today", action: { to: "review" } },
    { kind: "mistake_drill", title: "Drill sign errors", minutes: 10, reason: "3 sign errors in Integration in 30 days", action: { to: "mistakes", module_id: "m1" } },
    {
      kind: "topic", title: "Practise Integration", minutes: 20,
      reason: "est. 30% · last practised 6 days ago · MATH101 exam in 34 days",
      action: { to: "practice", module_id: "m1", topic_id: "t3", questions: 13 },
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

describe("today", () => {
  it("shows today's revision with its reasons, and plans 45 minutes", async () => {
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/plan": () => [200, plan],
      "GET /api/v1/recommendations": () => [200, [built.blocks[2]]],
      "GET /api/v1/session-builder": () => [200, built],
      "POST /api/v1/quizzes": () => [201, { quiz: {}, attempt_id: "a1" }],
      "GET /api/v1/attempts/a1": () => [404, { error: { code: "x", message: "x" } }],
    });
    const user = userEvent.setup();
    const router = renderAt("/");

    const revision = await screen.findByRole("region", { name: "Today's revision" });
    expect(await within(revision).findByText("Integration")).toBeInTheDocument();
    expect(within(revision).getByText(/est\. 30% · 4 mistakes in 30 days/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Upcoming exams" })).toHaveTextContent("in 34 days");
    const next = await screen.findByRole("region", { name: "Recommended next" });
    expect(next).toHaveTextContent("Practise Integration");
    expect(next).toHaveTextContent("est. 30% · last practised 6 days ago · MATH101 exam in 34 days");

    const builder = screen.getByRole("region", { name: "Got some time?" });
    await user.clear(within(builder).getByLabelText("I have"));
    await user.type(within(builder).getByLabelText("I have"), "45");
    await user.click(within(builder).getByRole("button", { name: "Plan it" }));
    const steps = await within(builder).findByRole("list", { name: "Your session" });
    expect(within(steps).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      expect.stringContaining("Review 12 due flashcards"),
      expect.stringContaining("3 sign errors in Integration"),
      expect.stringContaining("MATH101 exam in 34 days"),
    ]);
    expect(calls.find((c) => c.path === "/api/v1/session-builder")).toBeTruthy();

    const practise = within(steps).getAllByRole("listitem")[2]!;
    await user.click(within(practise).getByRole("button", { name: /Go/ }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/quizzes")?.body).toMatchObject({
        module_id: "m1",
        topic_ids: ["t3"],
        count: 13,
      }),
    );
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/attempts/a1"));
  });

  it("marks a planned session done", async () => {
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/plan": () => [200, plan],
      "POST /api/v1/sessions/s1/status": () => [200, { ...studySession, status: "done" }],
    });
    const user = userEvent.setup();
    renderAt("/");
    const revision = await screen.findByRole("region", { name: "Today's revision" });
    await user.click(await within(revision).findByRole("button", { name: "Mark Integration done" }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/sessions/s1/status")?.body).toEqual({ status: "done" }),
    );
  });
});

describe("planner page", () => {
  const availability = {
    weekdays: [120, 120, 120, 120, 120, 60, 60],
    custom: [false, false, false, false, false, false, false],
    overrides: [],
  };
  const preferences = {
    session_minutes: 45, max_sessions_per_day: 3, rest_weekdays: [], notify_exams: true,
    notify_quiz: true, notify_neglected: true, notify_flashcards: true, quiz_reminder_hour: 18,
    quiet_from: null, quiet_to: null,
  };

  it("turns your words into availability you confirm, and explains a shortfall", async () => {
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/plan": () => [
        200,
        {
          ...plan,
          shortfalls: [
            {
              exam_id: "e1", title: "MATH101 final", needed_minutes: 600, planned_minutes: 240,
              available_minutes: 240, left_out: ["Series"], reason: "time",
            },
          ],
        },
      ],
      "GET /api/v1/exams": () => [200, [exam]],
      "GET /api/v1/availability": () => [200, availability],
      "GET /api/v1/planner/preferences": () => [200, preferences],
      "POST /api/v1/availability/parse": () => [
        200,
        {
          weekdays: [180, 180, 180, 180, 180, null, null],
          dates: [{ day: addDays(today, 1), minutes: 0 }],
          note: "Weekdays 3 hours; busy tomorrow.",
        },
      ],
      "PUT /api/v1/availability": (_r, body) => [200, { ...availability, weekdays: (body as { weekdays: number[] }).weekdays.map((m, i) => m ?? availability.weekdays[i]) }],
    });
    const user = userEvent.setup();
    renderAt("/planner");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("MATH101 final: the plan can't cover everything.");
    expect(alert).toHaveTextContent("It needs about 10 h but you have 4 h before the exam.");
    expect(alert).toHaveTextContent("Less time for: Series.");

    await user.type(screen.getByLabelText("Describe it in your own words"), "3 hours on weekdays, busy tomorrow");
    await user.click(screen.getByRole("button", { name: /Suggest/ }));
    const proposal = await screen.findByRole("region", { name: "Proposed availability" });
    expect(proposal).toHaveTextContent("Every Monday: 3 h");
    expect(calls.some((c) => c.method === "PUT")).toBe(false); // nothing saved yet
    await user.click(within(proposal).getByRole("button", { name: "Use this" }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
        weekdays: [180, 180, 180, 180, 180, null, null],
        overrides: [{ day: addDays(today, 1), minutes: 0 }],
      }),
    );
    expect(screen.queryByRole("region", { name: "Proposed availability" })).toBeNull();
  });
});

describe("calendar", () => {
  it("moves a session to another day and marks one done", async () => {
    const start = weekStart(today);
    const days = Array.from({ length: 7 }, (_, i) => {
      const day = addDays(start, i);
      return {
        day, available_minutes: 120, exams: [], quizzes: [], reviews: 0, due_cards: 0,
        sessions: day === today ? [studySession] : [],
      };
    });
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/calendar": (request) => {
        const url = new URL(request.url);
        const wanted = days.filter((d) => d.day >= url.searchParams.get("start")! && d.day <= url.searchParams.get("end")!);
        return [200, { start: url.searchParams.get("start"), end: url.searchParams.get("end"), days: wanted }];
      },
      "PATCH /api/v1/sessions/s1": (_r, body) => [200, { ...studySession, ...(body as object), locked: true }],
      "POST /api/v1/sessions/s1/status": () => [200, { ...studySession, status: "done" }],
    });
    const user = userEvent.setup();
    renderAt("/calendar");

    const grid = await screen.findByRole("grid");
    expect(await within(grid).findByText("Integration")).toBeInTheDocument();
    // Open today in day view for the full controls.
    const todayCell = within(grid).getAllByRole("gridcell").find((c) => c.textContent?.includes("Integration"))!;
    await user.click(within(todayCell).getByRole("button", { name: String(new Date().getDate()) }));
    expect(await screen.findByText(/MATH101 exam in 34 days/)).toBeInTheDocument();

    const target = addDays(today, 2);
    const move = screen.getByLabelText("Move Integration to");
    await user.clear(move);
    await user.type(move, target);
    await user.click(screen.getByRole("button", { name: "Move" }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ day: target, minutes: null }),
    );
    await user.click(screen.getByRole("button", { name: /Done/ }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/sessions/s1/status")?.body).toEqual({ status: "done" }),
    );
  });
});

describe("notifications", () => {
  it("shows unread reminders and follows one", async () => {
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/notifications": () => [
        200,
        {
          unread: 1,
          items: [
            {
              id: 7, kind: "exam", title: "Your MATH101 exam is in 7 days.", body: "MATH101 final, Mon 12 Oct 09:00.",
              link: "/planner", read_at: null, created_at: new Date().toISOString(),
            },
          ],
        },
      ],
      "POST /api/v1/notifications/7/read": () => [204, null],
      "GET /api/v1/availability": () => [200, { weekdays: [0, 0, 0, 0, 0, 0, 0], custom: Array(7).fill(false), overrides: [] }],
      "GET /api/v1/planner/preferences": () => [
        200,
        {
          session_minutes: 45, max_sessions_per_day: 3, rest_weekdays: [], notify_exams: true, notify_quiz: true,
          notify_neglected: true, notify_flashcards: true, quiz_reminder_hour: 18, quiet_from: null, quiet_to: null,
        },
      ],
    });
    const user = userEvent.setup();
    const router = renderAt("/");
    await user.click(await screen.findByRole("button", { name: "Notifications, 1 unread" }));
    const panel = screen.getByRole("region", { name: "Notifications" });
    await user.click(within(panel).getByRole("button", { name: /exam is in 7 days/ }));
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/planner"));
    expect(calls.some((c) => c.path === "/api/v1/notifications/7/read")).toBe(true);
  });

  it("lets you switch reminders off in settings", async () => {
    const preferences = {
      session_minutes: 45, max_sessions_per_day: 3, rest_weekdays: [], notify_exams: true, notify_quiz: true,
      notify_neglected: true, notify_flashcards: true, quiz_reminder_hour: 18, quiet_from: null, quiet_to: null,
    };
    const { calls } = fakeApi({
      ...base,
      "GET /api/v1/planner/preferences": () => [200, preferences],
      "PATCH /api/v1/planner/preferences": (_r, body) => [200, { ...preferences, ...(body as object) }],
      "GET /api/v1/ai/budget": () => [
        200,
        {
          currency: "GBP", spent_today: 0, spent_this_month: 0, daily_cap: 2, monthly_cap: 10,
          warning: false, exhausted: false, configured: true,
        },
      ],
      "GET /api/v1/trash": () => [
        200,
        { modules: [], topics: [], documents: [], materials: [], flashcards: [], retention_days: 30 },
      ],
      "GET /api/v1/health/ready": () => [200, { status: "ready", checks: {} }],
    });
    const user = userEvent.setup();
    renderAt("/settings");
    const section = await screen.findByRole("region", { name: "Notifications" });
    await user.click(await within(section).findByLabelText("Lots of flashcards due"));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ notify_flashcards: false }),
    );
  });
});
