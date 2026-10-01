# Revision OS

A personal, AI-assisted university revision platform: upload lecture materials,
search and question them with cited answers, practise with adaptive quizzes and
flashcards, and plan revision around exams.

- Specification: [docs/SPEC.md](docs/SPEC.md)
- Approved design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Decisions: [docs/adr/](docs/adr/)

**Status:** Phase 3 (files). Phase 2 brought sign-in with secure sessions,
academic years, modules and topic trees, theming and settings. Phase 3 adds
uploading lecture materials, which are turned into page-by-page Markdown with
LaTeX maths; pages whose maths extracts badly are read by Claude, within a
monthly budget. Search and asking Claude questions arrive in Phases 4–5.

## Layout

```
backend/    FastAPI API + Arq worker (Python 3.12, uv)
  app/        api/v1/ (routers) → services/ (rules) → repositories/ (user-scoped
              data access) → models/; core/ (settings, config, security, errors)
  config/     learning.yaml, ai.yaml, platform.yaml — every tunable number,
              validated at startup
  migrations/ Alembic
  tests/      unit/, api/, db/
frontend/   React 18 + TypeScript SPA (Vite, pnpm, TanStack Router + Query)
  src/        app/ (router, shell), features/, components/, lib/ (API client)
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
make create-user            # in a second terminal: your account (asks for a password)
```

Registration is closed by design; `make create-user` is the only way to make
an account. Sign in at http://localhost:5173.

### Claude (maths transcription)

Add your Anthropic API key to `.env` as `ANTHROPIC_API_KEY=...`, then run
`make dev` again. Without a key everything still works: damaged maths pages
are kept as extracted and flagged "needs review". Spending is capped at
£10 a month (`backend/config/ai.yaml`); Settings → AI usage shows the total.

Transcription costs roughly 0.5p per slide and 1.5p per dense page of notes,
once per upload (a 110-page set of LaTeX notes is about £1.60). If the
monthly cap is reached part-way through, the remaining pages are flagged
"not transcribed: budget used up"; use **Reprocess** after it resets to finish
them. Transcribed and corrected pages are never redone.

### Uploading materials

Open a module and drop files on **Materials**: PDF, Word, PowerPoint, Excel,
CSV, text, Markdown, or photos (PNG, JPEG, WebP, HEIC). Each file is checked,
stored privately and processed in the background. Open a document to see each
page beside its transcription, correct anything by hand (corrections are
never overwritten), or ask Claude to re-read a page.

PowerPoint slides containing Office equation objects need LibreOffice to be
transcribed. It is optional because it adds about 500 MB to the image:

```bash
WITH_LIBREOFFICE=true make dev
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
| `ANTHROPIC_API_KEY` | Claude API key: maths transcription now, chat from Phase 5 (optional; see above) |

## Testing

```bash
make test           # backend + frontend
make check          # lint + typecheck + tests (what CI runs)
```

To check extraction on your own lecture files, put a few in `samples/`
(git-ignored: they are university copyright and the repo is public), then
`cd backend && uv run pytest -m samples -s`. This makes no AI calls.

Backend directly: `cd backend && uv run pytest`. Database tests need real
PostgreSQL + pgvector: they start one with Testcontainers when Docker is
running, or use `TEST_DATABASE_URL` if set. Without either they **skip** with
a reason locally; in CI a skip fails the build.

## Security model

Session cookies are HttpOnly and `__Host-` prefixed; tokens are stored only
as hashes; state-changing requests need a CSRF header; login is rate limited;
another user's data returns 404. Deletes go to a 30-day trash (restore from
Settings). Details: [ADR 7](docs/adr/0007-sessions-csrf-and-access-control.md).

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
Session lifetimes, login rate limits and trash retention are in
`platform.yaml`. Model IDs, per-task effort levels
([ADR 6](docs/adr/0006-per-task-effort-in-ai-routing.md)) and per-token prices
are in `ai.yaml`; update prices from
Anthropic's pricing page when they change. The AI spending caps there
(£10 a month, £2 a day, converted from USD at a deliberately cautious rate)
are enforced from Phase 5. For a hard ceiling outside the app as well, load
matching prepaid credit in the Claude Console with auto-reload off.
