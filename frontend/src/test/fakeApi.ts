/**
 * A tiny in-memory stand-in for the backend, routed by "METHOD /path".
 * Handlers return [status, body] — or a ready-made Response, e.g. a stream of
 * server-sent events. Unmatched requests fail the test loudly.
 */
import { vi } from "vitest";

export type Handler = (request: Request, body: unknown) => [number, unknown] | Promise<[number, unknown]>;

/** Reads every signed-in page makes in the background (the notifications
 *  bell, Today's plan); a test overrides them by naming the same route. */
const BACKGROUND: Record<string, Handler> = {
  "GET /api/v1/notifications": () => [200, { unread: 0, items: [] }],
  "GET /api/v1/plan": () => [
    200,
    { generated_at: "2026-10-05T09:00:00Z", starts: "2026-10-05", ends: "2026-10-19", shortfalls: [], today: [], upcoming: [], exams: [] },
  ],
  "GET /api/v1/exams": () => [200, []],
  "GET /api/v1/recommendations": () => [200, []],
  "GET /api/v1/push/config": () => [200, { enabled: false, public_key: null, devices: 0 }],
  "GET /api/v1/analytics/dashboard": () => [
    200,
    { panels: ["glance", "recommended", "todays_revision", "daily_quiz", "flashcards", "builder", "exams", "weak_topics", "mistakes", "recent"].map((key) => ({ key, reason: null })) },
  ],
  "GET /api/v1/analytics/overview": () => [
    200,
    {
      today: { progress: { value: null, basis: "No data yet" }, planned_minutes: 0, done_minutes: 0 },
      streak: { current: { value: null, basis: "No data yet" }, longest: { value: null, basis: "No data yet" } },
      recent: { days: 7, answered: { value: null, basis: "No data yet" }, correct: { value: null, basis: "No data yet" }, accuracy: { value: null, basis: "No data yet" }, study_minutes: { value: null, basis: "No data yet" }, reviews: { value: null, basis: "No data yet" }, mistakes: { value: null, basis: "No data yet" } },
      mastered: { value: null, basis: "No data yet" },
      mistake_groups: { value: null, basis: "No data yet" },
      modules: [],
      strong: [],
      weak: [],
      uploads: [],
      materials: [],
    },
  ],
  "GET /api/v1/analytics/modules/m1": () => [
    200,
    {
      module_id: "m1", progress: { value: null, basis: "No data yet" }, coverage: { value: null, basis: "No data yet" }, mastered: { value: null, basis: "No data yet" },
      recent: { days: 7, answered: { value: null, basis: "No data yet" }, correct: { value: null, basis: "No data yet" }, accuracy: { value: null, basis: "No data yet" }, study_minutes: { value: null, basis: "No data yet" }, reviews: { value: null, basis: "No data yet" }, mistakes: { value: null, basis: "No data yet" } }, readiness: null, recommendation: null,
    },
  ],
  "GET /api/v1/analytics/trends": () => [200, { weeks: [], days: [], mistake_labels: {}, basis: {} }],
};

export function fakeApi(overrides: Record<string, Handler>) {
  const routes = { ...BACKGROUND, ...overrides };
  const calls: { method: string; path: string; body: unknown }[] = [];
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    // jsdom's AbortSignal is not one Node's Request accepts; the fake ignores it.
    const request = input instanceof Request ? input : new Request(input, { ...init, signal: undefined });
    const path = new URL(request.url).pathname;
    const text = request.method === "GET" ? "" : await request.text();
    const body: unknown = text ? JSON.parse(text) : undefined;
    calls.push({ method: request.method, path, body });
    const handler = routes[`${request.method} ${path}`];
    if (!handler) throw new Error(`Unexpected request: ${request.method} ${path}`);
    const [status, payload] = await handler(request, body);
    if (payload instanceof Response) return payload;
    return new Response(status === 204 ? null : JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  return { calls, spy };
}

export const UNAUTHORISED: [number, unknown] = [
  401,
  { error: { code: "not_authenticated", message: "Please sign in.", request_id: "t" } },
];
