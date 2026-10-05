# Security audit (Phase 12)

Date: 2026-10-05 · Scope: the whole app as of Phase 11, against
ARCHITECTURE.md section 12 and the OWASP Top 10 (2021).

**Result: no open high-severity findings.** One high-severity finding (push
SSRF) was fixed. Two medium findings are deferred to Phase 13, where
deployment adds the hosting they depend on.

## Method

- Read every route for authentication, ownership checks, rate limits and
  input limits. A test walks the real route table, so new AI routes can't
  skip a limit (`tests/api/test_rate_limits.py`).
- Reviewed the existing controls and their tests: sessions, CSRF, IDOR
  (cross-user tests per resource since Phase 2), upload validation, prompt
  injection handling, the AI budget guard, and logging (no secrets, request
  bodies or file contents logged).
- Dependencies: `pip-audit` and `pnpm audit` (dev dependencies included).
- Secrets: a gitleaks scan of the full git history (also run in CI).
- Outbound requests: anything the server fetches or posts to on a user's
  behalf.
- The service worker and the browser-side code runtimes.

## Findings

| # | Finding | Severity | Status |
| --- | --- | --- | --- |
| 1 | **Push subscription SSRF.** A subscription's endpoint was any URL, and the scheduler POSTs to it, so a signed-in user could make the server send requests to internal addresses (Redis, Postgres, cloud metadata). | High | Fixed |
| 2 | **No per-account rate limits on expensive routes.** The budget guard capped AI spend, but a runaway client or stolen session could flood the worker queue and use the day's budget in seconds. | Medium | Fixed |
| 3 | **Trash never emptied.** Deleted items stayed in the database and storage indefinitely, against the 30-day retention the app promises. | Medium | Fixed |
| 4 | **Third-party code runtimes from a CDN.** Pyodide and WebR load from jsDelivr, so a compromised CDN could run code on the app's origin. | Medium | Deferred to Phase 13 |
| 5 | **No Content-Security-Policy on the web app.** The API sends a strict CSP; the single-page app is served by the Vite dev server and has none. | Medium | Deferred to Phase 13 |
| 6 | **Notification clicks could open any URL.** The service worker opened whatever URL a push payload carried. Payloads come only from this server, so this was defence in depth. | Low | Fixed |
| 7 | **Coding results are reported by the browser.** Exercises run client-side (by design: ARCHITECTURE.md section 9), so a user can fake their own pass. This affects only their own statistics. | Low | Accepted |
| 8 | **Vitest advisory** (dev dependency only, never shipped). | Low | Fixed |

### Fixes

1. **Push hosts are allow-listed** (`config/planner.yaml` `push_hosts`):
   the endpoint must be `https`, on port 443, without credentials, on one of
   the browser push services (FCM, Mozilla, Apple, Windows) or a subdomain of
   one. This is checked when subscribing (422 `not_push_service`) and again
   by the sender before every request, so a row stored before the fix can't
   be used. Tests cover internal addresses, lookalike hosts, odd ports and
   credentials.
2. **Rate limits per account** (`config/platform.yaml` `rate_limits`): 60
   AI requests and 40 uploads per 10 minutes, and 5 test pushes. Excess
   requests get a 429 saying when to retry. All 14 routes that call Claude,
   upload or push are covered, and the route-table test fails if a new one
   isn't.
3. **The scheduler empties the trash daily** (`app/trash.py`, 03:17 UTC):
   items deleted more than 30 days ago are removed for good, children first,
   and then their stored files.
4. **Notification clicks open same-origin pages only.**
5. **Vitest upgraded to 4.1.11.**

### Deferred to Phase 13 (deployment)

- **Self-host the code runtimes** from the app's own origin with
  Subresource Integrity, so no third party can change the code that runs.
- **A CSP for the web app**, set by the production web server that Phase 13
  adds (`script-src 'self' 'wasm-unsafe-eval'`; no inline scripts).

Neither is exploitable without compromising jsDelivr or finding an
injection bug first. React escapes output, Markdown is sanitised, and no
known injection exists.

## Checked and sound

- **Sessions:** httpOnly, Secure and SameSite=Lax cookies; CSRF token on
  every unsafe method; login rate-limited per IP and per email.
- **Access control:** every query is scoped to the user; cross-user tests
  for every resource type.
- **Security headers:** nosniff, `X-Frame-Options: DENY`, no referrer, and
  a strict API CSP. The API docs are off in production.
- **Uploads:** type sniffed from content, size limits, duplicate check,
  files stored outside the web root under user-scoped keys.
- **AI:** document text and student work go in as data, never as
  instructions. Deletions need the user's confirmation. Daily and monthly
  spend caps are enforced before every call. Tutor requests never contain
  the reference solution.
- **Secrets:** only in `.env` (git-ignored). Nothing in history. The VAPID
  private key is never printed.
- **Dependencies:** `pip-audit` and `pnpm audit` clean.
