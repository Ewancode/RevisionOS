# API

A REST API under `/api/v1`, used only by the app itself (there are no third
party clients). The full, always-current reference is the OpenAPI schema:

- in development, browse it at http://localhost:8000/api/docs;
- it is committed as `frontend/openapi.json`, from which the frontend's types
  are generated (`make api-client`). Tests and CI fail if either is stale.

In production the documentation pages are switched off.

## Conventions

**Signing in.** `POST /api/v1/auth/login` sets two cookies: the session
(`__Host-rev_session`, HttpOnly) and a CSRF token (`__Host-rev_csrf`, readable
by the page). Every request that changes something (`POST`, `PUT`, `PATCH`,
`DELETE`) must send that token back in the `X-CSRF-Token` header. Both cookies
are Secure, so outside `localhost` the app needs HTTPS.

**Ownership.** Every resource belongs to the signed-in user. Another user's
id answers `404`, exactly like an id that doesn't exist.

**Errors** always use one shape and never include a stack trace:

```json
{ "error": { "code": "not_found", "message": "That module does not exist.", "request_id": "…" } }
```

`code` is stable and meant for the app; `message` is written for people. Some
errors add `details` (for example the existing document's id on a duplicate
upload). Common statuses: `401` not signed in, `403` CSRF token missing,
`404` not found (or not yours), `409` conflicts with the current state,
`413` too large, `422` invalid input, `429` rate-limited or the AI budget
is used up (the message says which, and when to retry), `502` Claude's
answer was unusable, `503` Claude is not set up or not reachable.

**Request ids.** Every response carries `X-Request-ID`, and every log line for
that request includes it (logs are JSON on stdout).

**Uploads** are the raw file as the request body, with details in the query
string, e.g. `POST /api/v1/documents?filename=L1.pdf&module_id=…`. Restoring
an export works the same way (`POST /api/v1/export/restore`).

**Long-running work** returns `202 Accepted` and continues in the background
worker: uploads (follow `GET /api/v1/documents/{id}/events`, server-sent
events), generated drafts, marking, exports and restores (poll the resource).
The assistant's answers stream as server-sent events.

**Times** are ISO 8601 with a time zone (UTC from the server). Days without a
time (`2026-10-06`) are in your own time zone.

## Areas

| Prefix | What |
| --- | --- |
| `/auth`, `/settings` | Signing in and out, your account and preferences |
| `/years`, `/modules`, `/topics`, `/trash` | Academic structure, and restoring deleted items |
| `/documents`, `/search` | Uploads, pages, corrections; hybrid search |
| `/conversations`, `/pending-actions`, `/ai` | The assistant, confirmations, AI usage and budget |
| `/materials`, `/drafts`, `/questions`, `/flashcards`, `/quizzes`, `/attempts`, `/answers` | Revision materials, practice and marking |
| `/daily-quiz`, `/progress`, `/mistakes`, `/profile` | Adaptive learning |
| `/exams`, `/availability`, `/planner`, `/plan`, `/sessions`, `/calendar`, `/session-builder`, `/recommendations`, `/notifications`, `/push` | The planner and reminders |
| `/analytics` | Dashboards and trends |
| `/coding` | Coding exercises, submissions and the tutor |
| `/export` | Exports of your data, and restores |
| `/health`, `/health/ready` | Liveness, and readiness (database and Redis) |
