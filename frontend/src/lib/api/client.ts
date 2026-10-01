import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

const CSRF_COOKIE = "__Host-rev_csrf";
const CSRF_HEADER = "X-CSRF-Token";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export function readCookie(name: string): string | undefined {
  for (const part of document.cookie.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return undefined;
}

/** Echo the CSRF cookie in a header on state-changing requests (ARCHITECTURE.md §12). */
export const csrfMiddleware: Middleware = {
  onRequest({ request }) {
    if (!SAFE_METHODS.has(request.method)) {
      const token = readCookie(CSRF_COOKIE);
      if (token) request.headers.set(CSRF_HEADER, token);
    }
    return request;
  },
};

/** The backend's error envelope, as a throwable. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface Envelope {
  error?: { code?: string; message?: string; request_id?: string };
}

export function toApiError(status: number, body: unknown): ApiError {
  const error = (body as Envelope | undefined)?.error;
  return new ApiError(
    status,
    error?.code ?? "unknown_error",
    error?.message ?? "Something went wrong. Please try again.",
    error?.request_id,
  );
}

/**
 * Typed API client generated from the backend's OpenAPI schema.
 * Regenerate with `make api-client`; a backend change that breaks a call here
 * fails `pnpm typecheck`.
 */
export const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? "",
  credentials: "same-origin",
  // Resolve fetch per call so tests can stub it.
  fetch: (request) => globalThis.fetch(request),
});
api.use(csrfMiddleware);

/** Return `data`, or throw the error envelope as an ApiError. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (error !== undefined || !response.ok) throw toApiError(response.status, error);
  return data as T;
}
