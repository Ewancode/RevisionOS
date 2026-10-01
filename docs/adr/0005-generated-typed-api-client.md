# 5. Typed frontend client generated from the OpenAPI schema

Date: 2026-10-01 · Status: Accepted (ARCHITECTURE.md section 3)

## Context

The design requires that a backend change which breaks the frontend fails the
build.

## Decision

- `scripts/export_openapi.py` writes the FastAPI schema to
  `frontend/openapi.json` without starting the app.
- `openapi-typescript` generates `src/lib/api/schema.d.ts`; `openapi-fetch`
  provides a small, fully typed client over it. No runtime code generation.
- Both files are committed. A backend test fails if `openapi.json` is stale,
  and CI fails if `schema.d.ts` differs from a fresh generation. `make
  api-client` regenerates both.

## Consequences

API drift shows up as a TypeScript error at build time. The interactive docs
and `/api/openapi.json` are served in development only.
