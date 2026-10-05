# Revision OS

A personal, AI-assisted university revision platform: upload lecture materials,
search and question them with cited answers, practise with adaptive quizzes and
flashcards, and plan revision around exams.

- Specification: [docs/SPEC.md](docs/SPEC.md)
- Approved design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Decisions: [docs/adr/](docs/adr/)

**Status:** Phase 12 (hardening). Phase 2 brought
sign-in with secure sessions, academic years, modules and topic trees,
theming and settings.
Phase 3 added uploading lecture materials, which are turned into page-by-page
Markdown with LaTeX maths; pages whose maths extracts badly are read by
Claude, within a monthly budget. Phase 4 added search across your materials
(Ctrl+K anywhere), with each result linking to the exact page. Phase 5 adds
**Ask Claude**: questions answered from your materials, with every claim
linked to the page it came from, a badge saying whether the answer is from
your university material, your notes or general knowledge, and deletions
that happen only when you confirm them. An AI usage page shows cost by
feature, model, module and day. Phase 6 adds revision materials with version
history, a question bank and flashcards that Claude writes from your
materials (checked before you can save them), quizzes and timed mock exams
with AI help switched off, and marking of every answer type, including
photos of handwritten working, with explanations of every mistake. Phase 7
makes practice adaptive: a daily quiz that leans towards your weak topics and
recurring mistakes (explaining why), flashcards scheduled by FSRS, a topic
strength estimate shown with its evidence, a mistake bank and a learning
profile built only from what you did. Phase 8 adds the revision planner:
add your exams and when you can revise (or describe it in words), and it
spreads sessions before each exam, weakest topics first, with a mock exam a
few days before and a reason for every session. It replans as you practise,
keeps sessions you move, says plainly when there isn't enough time, and
answers "I have 45 minutes" with an explained session. A calendar shows the
plan, quizzes and reviews; reminders appear under the bell. Phase 9 adds
analytics: Today shows your streak, today's progress, this week's questions,
accuracy and study time; each module gets an overview; and an Analytics page
charts accuracy, study time, mistakes and consistency by week, with exam
readiness built from measured components (never a predicted mark). Every
figure says what it was computed from. Phase 10 adds coding practice:
Python and R exercises that run and mark in your browser (Pyodide and
WebR), written by you or by Claude (whose reference solutions are checked
against their own tests before saving), and a tutor that gives hints one
step at a time, also on practice-quiz questions. Phase 11 polishes it: a
command palette (Ctrl+K) and keyboard shortcuts (press ?), a phone layout,
an installable app with push reminders (run `make vapid-keys` once to turn
push on; phones need HTTPS, so phone push comes with deployment), Today's
panels ordered by what is pressing, and an accessibility pass checked with
axe. Phase 12 hardens it: a security audit
([docs/security-audit.md](docs/security-audit.md)) with per-account rate
limits, push sent only to real push services and the trash emptied after 30
days; performance targets checked on a seeded heavy year; and the full AI
evaluations ([ADR 18](docs/adr/0018-hardening-limits-purge-performance.md)).
The formulas are in [docs/algorithms.md](docs/algorithms.md).

## Layout

```
backend/    FastAPI API + Arq worker and scheduler (Python 3.12, uv)
  app/        api/v1/ (routers) → services/ (rules) → repositories/ (user-scoped
              data access) → models/; core/ (settings, config, security, errors)
  config/     learning.yaml, planner.yaml, analytics.yaml, coding.yaml, ai.yaml, platform.yaml — every tunable number,
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
make dev                    # db, redis, api, worker, scheduler, frontend
make create-user            # in a second terminal: your account (asks for a password)
```

Registration is closed by design; `make create-user` is the only way to make
an account. Sign in at http://localhost:5173.

### Claude (the assistant and maths transcription)

Add your Anthropic API key to `.env` as `ANTHROPIC_API_KEY=...`, then run
`make dev` again. Without a key everything else still works: the assistant
says it is not configured, and damaged maths pages are kept as extracted and
flagged "needs review". Spending is capped at £10 a month and £2 a day
(`backend/config/ai.yaml`); the AI usage page (`/usage`) shows where it went.

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
| `ANTHROPIC_API_KEY` | Claude API key for the assistant and maths transcription (optional; see above) |

## Testing

```bash
make test           # backend + frontend
make check          # lint + typecheck + tests (what CI runs)
```

Search quality: `make eval-search` scores the live index against a golden
set of questions in `samples/golden.yaml` (git-ignored; format in
`backend/scripts/eval_search.py`). `make reindex` rebuilds the search index,
for example after changing `config/retrieval.yaml` or the embedding model
(see [ADR 10](docs/adr/0010-retrieval-details.md)).

Answer quality: `make eval-chat` asks a spread of the golden questions
through the real assistant and checks that its verified citations point at
the expected pages ([ADR 11](docs/adr/0011-assistant-chat-and-citations.md)).
It makes real API calls, so on its own it only prints the estimated cost
(about £0.30 for the default 10 questions); run `make eval-chat ARGS=--yes`
to go ahead. Automated tests never call the real API.

Practice quality: `make eval-practice ARGS="--yes --module MATH101"` generates
questions through the real API, reports how many pass the app's checks, then
marks a right and a wrong answer to each with the real marking pipeline
([ADR 12](docs/adr/0012-revision-materials-questions-and-marking.md)). It
cleans up after itself and costs about £0.20.

Content quality: `make eval-content ARGS=--yes` generates questions and
has a second model (Haiku) judge whether each answer is supported by the
passages it cites (target 90%). It also checks for near-duplicates and
coding exercises, and asks the tutor for rungs 1-3 on a few questions to
check that no hint states the answer. Cleans up after itself; about £0.15.

Performance: `make perf` seeds a separate database with a heavy year of use
(once), then times every main endpoint and a burst of 8 clients against the
targets in `config/platform.yaml` `performance`. No API calls; a few
minutes.

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
are checked before every call. The assistant's limits (calls per answer,
history length, how long delete requests wait for you) are in its `chat`
section. For a hard ceiling outside the app as well, load
matching prepaid credit in the Claude Console with auto-reload off.
Generation limits, the checks on generated questions, marking tolerances and
quiz and exam settings are in `practice.yaml`; search settings are in
`retrieval.yaml`; the adaptive-learning formulas' numbers (strength, Elo,
FSRS, the daily quiz's weights, mistake patterns) are in `learning.yaml`.
