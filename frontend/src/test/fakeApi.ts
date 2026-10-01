/**
 * A tiny in-memory stand-in for the backend, routed by "METHOD /path".
 * Handlers return [status, body]; unmatched requests fail the test loudly.
 */
import { vi } from "vitest";

export type Handler = (request: Request, body: unknown) => [number, unknown] | Promise<[number, unknown]>;

export function fakeApi(routes: Record<string, Handler>) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    const text = request.method === "GET" ? "" : await request.text();
    const body: unknown = text ? JSON.parse(text) : undefined;
    calls.push({ method: request.method, path, body });
    const handler = routes[`${request.method} ${path}`];
    if (!handler) throw new Error(`Unexpected request: ${request.method} ${path}`);
    const [status, payload] = await handler(request, body);
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
