# Revision OS

A personal, AI-assisted university revision platform: upload lecture materials,
search and question them with cited answers, practise with adaptive quizzes and
flashcards, and plan revision around exams.

- Specification: [docs/SPEC.md](docs/SPEC.md)
- Approved design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Decisions: [docs/adr/](docs/adr/)

**Status:** Phase 1 (scaffold) — an empty app with health checks, config
loading, migrations, tests and CI. Features arrive from Phase 2.

## Layout

```
backend/    FastAPI API + Arq worker (Python 3.12, uv)
  app/        core/ (settings, config, logging, errors), db/, api/v1/, workers/
  config/     learning.yaml, ai.yaml — every tunable number, validated at startup
  migrations/ Alembic
  tests/      unit/, api/, db/
frontend/   React 18 + TypeScript SPA (Vite, pnpm)
infra/      docker-compose.yml, backend.Dockerfile
docs/       spec, architecture, ADRs
```

## Prerequisites

- **Docker Desktop** — runs PostgreSQL (pgvector), Redis and the app
- **GNU Make** — on Windows: `winget install ezwinports.make`, or run the
  commands in the `Makefile` directly
- For running tools on the host: **Python 3.12** with [uv](https://docs.astral.sh/uv/),
  and **Node 22 LTS** with pnpm (`corepack enable`)

## Quick start

```bash
cp .env.example .env        # then set POSTGRES_PASSWORD (and DATABASE_URL to match)
make dev                    # db, redis, api, worker, frontend
```

- App: http://localhost:5173
- API docs (development only): http://localhost:8000/api/docs
- Liveness: `GET /api/v1/health` · Readiness (database + Redis): `GET /api/v1/health/ready`

The API applies migrations on start. To run them by hand: `make migrate`.

## Environment variables

All documented in [.env.example](.env.example). `.env` is git-ignored — never
commit it. Keep `ANTHROPIC_API_KEY` in `.env` only; if it is exported in your
shell, Claude Code bills that key instead of your Pro plan.

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | `development`, `test` or `production` (production hides API docs) |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Database created by compose |
| `DATABASE_URL` | Async SQLAlchemy URL used when running on the host |
| `REDIS_URL` | Job queue and (later) rate limits |
| `ANTHROPIC_API_KEY` | Needed from Phase 5 |

## Testing

```bash
make test           # backend + frontend
make check          # lint + typecheck + tests (what CI runs)
```

Backend directly: `cd backend && uv run pytest`. Database tests need real
PostgreSQL + pgvector: they start one with Testcontainers when Docker is
running, or use `TEST_DATABASE_URL` if set. Without either they **skip** with
a reason locally; in CI a skip fails the build.

## API conventions

REST under `/api/v1`. Every error uses one envelope and never includes a stack
trace:

```json
{ "error": { "code": "not_found", "message": "Not Found", "request_id": "…" } }
```

Each response carries `X-Request-ID`, which also appears on every log line
for that request (logs are JSON on stdout).

The frontend's API types are generated from the backend schema. After changing
an endpoint, run `make api-client` and commit `frontend/openapi.json` and
`frontend/src/lib/api/schema.d.ts`; tests and CI fail if they are stale.

## Configuration

Tunable numbers live in `backend/config/*.yaml`, never in code, and are
validated on startup (see [ADR 4](docs/adr/0004-validated-yaml-configuration.md)).
Model IDs and per-token prices are in `ai.yaml`; update prices from
Anthropic's pricing page when they change. The AI spending caps there
(`daily_usd_cap`, `monthly_usd_cap`) are enforced from Phase 5.
