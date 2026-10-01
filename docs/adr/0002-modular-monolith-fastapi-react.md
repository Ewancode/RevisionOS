# 2. Modular monolith: FastAPI backend, React SPA, Arq worker

Date: 2026-10-01 · Status: Accepted (ARCHITECTURE.md sections 1, 3, 4)

## Context

One user, one developer, heavy document and maths processing, and a need to
run on a laptop and deploy unchanged later.

## Decision

- One FastAPI application (`backend/app`) split into domain packages behind
  interfaces, plus one Arq worker process sharing the same code.
- A React + TypeScript SPA built by Vite, talking only to `/api/v1`.
- In development Vite proxies `/api` to the backend, so the browser sees one
  origin — no CORS, and cookies behave as they will in production.
- The cron `scheduler` process is added in the first phase with a scheduled
  job; Phase 1 has none.

## Consequences

Single deployable, single database transaction boundary, simple local setup.
Package boundaries keep a later split possible.
