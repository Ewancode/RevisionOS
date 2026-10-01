import createClient from "openapi-fetch";

import type { paths } from "./schema";

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
