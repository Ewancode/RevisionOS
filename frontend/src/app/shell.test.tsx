import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { fakeApi, type Handler } from "@/test/fakeApi";

import { routeTree } from "./router";

const module = {
  id: "m1", academic_year_id: "y1", code: "MATH101", title: "Calculus I",
  subject_tag: null, credits: 15, colour: null, status: "active",
};
const base: Record<string, Handler> = {
  "GET /api/v1/auth/session": () => [200, { user: { id: "u1", email: "e@example.com", display_name: "Ewan" }, settings: { theme: "light", accent_colour: "#4f46e5" } }],
  "GET /api/v1/years": () => [200, [{ id: "y1", label: "2026/27", start_date: "2026-09-21", end_date: "2027-06-12", is_current: true }]],
  "GET /api/v1/modules": () => [200, [module]],
  "GET /api/v1/modules/m1": () => [200, module],
  "GET /api/v1/daily-quiz/plan": () => [200, { minutes: 15, seconds_per_question: 90, questions: 10, buckets: [] }],
  "GET /api/v1/flashcards/due": () => [200, { cards: [], counts: { due: 0, review: 0, learning: 0, new: 0 } }],
  "GET /api/v1/progress/weakest": () => [200, []],
  "GET /api/v1/mistakes": () => [200, []],
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

describe("the command palette", () => {
  it("finds a module's actions by typing its code, and runs them", async () => {
    const { calls } = fakeApi({
      ...base,
      "POST /api/v1/quizzes": () => [201, { quiz: {}, attempt_id: "a9" }],
      "GET /api/v1/attempts/a9": () => [404, { error: { code: "x", message: "x" } }],
    });
    const user = userEvent.setup();
    const router = renderAt("/");
    await screen.findByRole("heading", { level: 1 });
    await user.keyboard("{Control>}k{/Control}");
    const palette = await screen.findByRole("dialog", { name: "Command palette" });
    await user.keyboard("math101 mock");
    // Typing narrows the list to the matching action (plus search and Ask Claude).
    expect(within(palette).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Search your materials for “math101 mock”",
      "Ask Claude",
      "MATH101: start a mock exam",
    ]);
    await user.click(within(palette).getByRole("option", { name: /MATH101: start a mock exam/ }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/quizzes")?.body).toEqual({ module_id: "m1", kind: "mock" }),
    );
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/attempts/a9"));
    expect(screen.queryByRole("dialog", { name: "Command palette" })).toBeNull();
  });

  it("searches your materials for whatever you type", async () => {
    fakeApi({
      ...base,
      "GET /api/v1/search": () => [
        200,
        { query: "ratio test", scope_used: "all", widened: false, passages: [], modules: [], topics: [], documents: [] },
      ],
    });
    const user = userEvent.setup();
    const router = renderAt("/");
    await screen.findByRole("heading", { level: 1 });
    await user.click(screen.getByRole("button", { name: /Commands/ }));
    await user.keyboard("ratio test");
    await user.click(await screen.findByRole("option", { name: /Search your materials for “ratio test”/ }));
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/search"));
    expect(router.state.location.search).toMatchObject({ q: "ratio test" });
    expect(await screen.findByText("No matches in your materials.")).toBeInTheDocument();
  });
});

describe("keyboard shortcuts", () => {
  it("goes places with g, asks Claude about the module with Ctrl+J, and lists them with ?", async () => {
    fakeApi({
      ...base,
      "GET /api/v1/availability": () => [200, { weekdays: Array(7).fill(60), custom: Array(7).fill(false), overrides: [] }],
      "GET /api/v1/planner/preferences": () => [200, { session_minutes: 45, max_sessions_per_day: 3, rest_weekdays: [], notify_exams: true, notify_quiz: true, notify_neglected: true, notify_flashcards: true, quiz_reminder_hour: 18, quiet_from: null, quiet_to: null }],
      "GET /api/v1/conversations": () => [200, []],
      "GET /api/v1/ai/budget": () => [200, { currency: "GBP", spent_today: 0, spent_this_month: 0, daily_cap: 2, monthly_cap: 10, warning: false, exhausted: false, configured: true }],
      "GET /api/v1/documents": () => [200, []],
      "GET /api/v1/modules/m1/topics": () => [200, []],
      "GET /api/v1/progress": () => [200, []],
      "GET /api/v1/drafts": () => [200, []],
    });
    const user = userEvent.setup();
    const router = renderAt("/y/y1/m/m1");
    await screen.findByRole("heading", { level: 1, name: "Calculus I" });

    await user.keyboard("{Control>}j{/Control}");
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/chat"));
    expect(router.state.location.search).toEqual({ module_id: "m1" });

    await user.click(document.body);
    await user.keyboard("gp");
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/planner"));

    // Typing in a field never triggers a shortcut.
    const search = screen.getByRole("searchbox", { name: "Search your materials" });
    await user.type(search, "gt");
    expect(router.state.location.pathname).toBe("/planner");

    await user.click(document.body);
    await user.keyboard("?");
    const help = await screen.findByRole("dialog", { name: "Keyboard shortcuts" });
    expect(help).toHaveTextContent("Command palette");
  });
});

describe("Today", () => {
  it("puts the pressing panels first and says why", async () => {
    fakeApi({
      ...base,
      "GET /api/v1/analytics/dashboard": () => [
        200,
        { panels: ["daily_quiz", "glance", "recommended", "todays_revision", "flashcards", "builder", "exams", "weak_topics", "mistakes", "recent"].map((key) => ({ key, reason: key === "daily_quiz" ? "Today's quiz is not done yet" : null })) },
      ],
    });
    renderAt("/");
    const daily = await screen.findByRole("region", { name: "Daily quiz" });
    await vi.waitFor(() =>
      expect(document.querySelector("[data-panel]")?.getAttribute("data-panel")).toBe("daily_quiz"),
    );
    expect(daily.parentElement).toHaveTextContent("Today's quiz is not done yet");
  });
});

describe("push notifications in settings", () => {
  it("explains when the server is not set up for push", async () => {
    fakeApi({
      ...base,
      "GET /api/v1/planner/preferences": () => [200, { session_minutes: 45, max_sessions_per_day: 3, rest_weekdays: [], notify_exams: true, notify_quiz: true, notify_neglected: true, notify_flashcards: true, quiz_reminder_hour: 18, quiet_from: null, quiet_to: null }],
      "GET /api/v1/ai/budget": () => [200, { currency: "GBP", spent_today: 0, spent_this_month: 0, daily_cap: 2, monthly_cap: 10, warning: false, exhausted: false, configured: true }],
      "GET /api/v1/trash": () => [200, { modules: [], topics: [], documents: [], materials: [], flashcards: [], exercises: [], retention_days: 30 }],
      "GET /api/v1/health/ready": () => [200, { status: "ready", checks: {} }],
    });
    renderAt("/settings");
    const device = await screen.findByRole("group", { name: "Notifications on this device" });
    // jsdom has no PushManager, like an unsupported browser.
    expect(device).toHaveTextContent("This browser cannot receive push notifications.");
  });
});
