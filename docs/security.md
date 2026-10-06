# Security

How Revision OS protects your account and data, what was audited, and what
risk remains. The design is in ARCHITECTURE.md section 12; decisions are in
ADRs 7, 8, 18 and 19.

## The security model

- **Accounts:** registration is closed (`make create-user`). Passwords are
  hashed with Argon2; login is rate-limited per IP address and per email.
- **Sessions:** `__Host-` cookies that are HttpOnly, Secure and
  SameSite=Lax. Session tokens are stored only as hashes. Every request that
  changes something needs a CSRF header.
- **Access control:** every query is scoped to the signed-in user. Another
  user's data answers 404, the same as data that doesn't exist, so ids can't
  be probed. Tests try every route that takes an id as a second user
  (`tests/api/test_access_control.py`).
- **Files:** uploads are checked by content (not by name), size-limited and
  stored under keys built only from server-made ids, never from your file
  names. They are served only through the API after an ownership check, as
  downloads. A bucket, when used, is private.
- **Claude:** document text and your work go to Claude as data, never as
  instructions. Deletions it proposes wait for your confirmation. Spend caps
  are checked before every call, and per-account rate limits stop bursts.
- **Deletion:** deletes go to a 30-day trash, emptied daily after that.
- **Secrets** live only in `.env` (git-ignored, never printed). CI scans the
  whole git history for secrets (gitleaks) and audits dependencies.

### In production (Phase 13)

- **Only the web server is exposed** (ports 80 and 443). The database, Redis
  and the API are on Docker's internal network. HTTPS certificates are
  automatic; HSTS is on.
- **A strict Content-Security-Policy** on every page (`infra/Caddyfile`):
  scripts only from the app's own origin, no `eval`, no inline scripts, no
  framing, and network access only to the app itself plus the two package
  sources for coding practice. A test keeps it in step with
  `config/coding.yaml` (`tests/unit/test_deployment.py`).
- **No third party serves code to your browser.** The Python (Pyodide) and R
  (WebR) runtimes are downloaded when the image is built, checked against
  pinned SHA-256 checksums (`frontend/scripts/fetch-runtimes.sh`), and served
  from the app's own origin.
- **Restoring an export can't reach anyone else's data:** a restore gives
  every row a new id and your user id, refuses an archive that refers to
  anything not in it, checks every value against its column's type, refuses
  zip bombs and unsafe paths, and writes files only to keys it builds itself
  (`app/export/restore.py`).
- **The API documentation is switched off**, and the API sends its own strict
  headers (it only returns JSON).

### Remaining risks (accepted)

| Risk | Why it is accepted |
| --- | --- |
| **R packages are not checksum-verified.** An exercise that names R packages installs them from the WebR project's repository (`repo.r-wasm.org`). | Only when an exercise asks for packages; the code runs inside R's worker, not on the page. Python packages, by contrast, are verified against the self-hosted Pyodide lock file. |
| **The R worker may use `eval`.** WebR links R's libraries with it, so `/runtimes/webr/*` gets a CSP that allows it. | That policy applies to R's worker only; the app's pages never allow `eval`. |
| **Coding results are reported by your browser.** | By design (code runs in your browser): you can only fake your own statistics. |

## Audit (Phase 12, 2026-10-05)

Scope: the whole app as of Phase 11, against ARCHITECTURE.md section 12 and
the OWASP Top 10 (2021).

**Result: no open high-severity findings.** The one high-severity finding
(push SSRF) was fixed, and both medium findings deferred to deployment were
fixed in Phase 13.

### Method

- Read every route for authentication, ownership checks, rate limits and
  input limits. A test walks the real route table, so new AI routes can't
  skip a limit (`tests/api/test_rate_limits.py`).
- Reviewed the existing controls and their tests: sessions, CSRF, IDOR,
  upload validation, prompt injection handling, the AI budget guard, and
  logging (no secrets, request bodies or file contents logged).
- Dependencies: `pip-audit` and `pnpm audit` (dev dependencies included).
- Secrets: a gitleaks scan of the full git history.
- Outbound requests: anything the server fetches or posts to on a user's
  behalf.
- The service worker and the browser-side code runtimes.

### Findings

| # | Finding | Severity | Status |
| --- | --- | --- | --- |
| 1 | **Push subscription SSRF.** A subscription's endpoint was any URL, and the scheduler POSTs to it, so a signed-in user could make the server send requests to internal addresses (Redis, Postgres, cloud metadata). | High | Fixed |
| 2 | **No per-account rate limits on expensive routes.** A runaway client or stolen session could flood the worker queue and use the day's AI budget in seconds. | Medium | Fixed |
| 3 | **Trash never emptied.** Deleted items stayed indefinitely, against the promised 30 days. | Medium | Fixed |
| 4 | **Code runtimes from a CDN.** Pyodide and WebR loaded from third-party CDNs, so a compromised CDN could run code on the app's origin. | Medium | Fixed (Phase 13) |
| 5 | **No Content-Security-Policy on the web app.** | Medium | Fixed (Phase 13) |
| 6 | **Notification clicks could open any URL.** Payloads come only from this server, so this was defence in depth. | Low | Fixed |
| 7 | **Coding results are reported by the browser.** | Low | Accepted |
| 8 | **Vitest advisory** (dev dependency only, never shipped). | Low | Fixed |

### Fixes

1. **Push hosts are allow-listed** (`config/planner.yaml` `push_hosts`): the
   endpoint must be `https`, on port 443, without credentials, on one of the
   browser push services (FCM, Mozilla, Apple, Windows) or a subdomain of
   one. Checked when subscribing (422 `not_push_service`) and again before
   every send. Tests cover internal addresses, lookalike hosts, odd ports and
   credentials.
2. **Rate limits per account** (`config/platform.yaml` `rate_limits`): 60
   requests that call Claude and 40 uploads per 10 minutes, 5 test pushes,
   and 6 exports or restores an hour. Excess requests get a 429 saying when
   to retry.
3. **The scheduler empties the trash daily** (`app/trash.py`).
4. **Self-hosted runtimes** with pinned checksums (Phase 13, above). WebR's
   GitHub release archive turned out not to be the build its site serves (it
   reports itself as a development version), so the site's files are pinned
   one by one instead (`frontend/scripts/webr-0.6.0.sha256`).
5. **A strict CSP** set by the production web server (Phase 13, above).
6. **Notification clicks open same-origin pages only.**
7. **Vitest upgraded to 4.1.11.**
8. **KaTeX** (Phase 13): a low-severity advisory (GHSA-238p-pmpm-9mq7)
   appeared in the copies of KaTeX that `rehype-katex` and `remark-math`
   bring in. A pnpm override now makes them use the app's own KaTeX 0.19,
   so one patched version both renders and styles the maths.
