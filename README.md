# Revision OS

A personal, AI-assisted university revision platform. Upload your lecture
materials, search them and ask questions with answers that cite the page they
came from, practise with adaptive quizzes, flashcards and coding exercises,
and plan your revision around your exams.

**Status:** complete (all 13 phases of [the plan](docs/ARCHITECTURE.md)).
It runs on your computer with Docker, and can be deployed to a small server
with HTTPS ([docs/deployment.md](docs/deployment.md)).

## What it does

- **Your materials:** PDF, Word, PowerPoint, Excel, text and photos become
  searchable page-by-page Markdown with LaTeX maths. Pages whose maths
  extracts badly are read by Claude; you can correct any page by hand.
- **Search and Ask Claude** (Ctrl+K): hybrid keyword and meaning search, and
  answers built from your materials, every claim linked to its page.
- **Practice:** revision materials, a question bank and flashcards written
  from your materials (checked before you can save them), quizzes and timed
  mock exams, marking of every answer type including photos of handwritten
  working, and a mistake bank.
- **Adaptive learning:** flashcards scheduled by FSRS, a daily quiz that leans
  towards weak topics, topic strength shown with its evidence.
- **Planner:** exams and availability in, a revision plan out, with a reason
  for every session; "I have 45 minutes" builds one on the spot.
- **Analytics:** streaks, accuracy and study time by week, exam readiness from
  measured components. Every figure says what it was computed from.
- **Coding practice:** Python and R exercises that run in your browser, with
  a tutor that gives hints one step at a time.
- **Your data is yours:** export everything as one ZIP (Markdown, CSV, an
  Anki deck and your files) and restore it into an empty account
  (Settings > Your data).

## Quick start (on your computer)

You need **Docker Desktop** and **Git**. **GNU Make** is optional (on
Windows: `winget install ezwinports.make`); without it, run the command each
`make` target shows in the [Makefile](Makefile).

```bash
git clone https://github.com/Ewancode/RevisionOS.git
cd RevisionOS
cp .env.example .env
make dev
```

`make dev` builds and starts everything: PostgreSQL with pgvector, Redis, the
API, the background worker and scheduler, and the web app. The first start
takes a few minutes: it downloads the Python and R runtimes for coding
practice (about 60 MB, checked against pinned checksums) and the search
model (about 70 MB). It is ready when the log shows `Local: http://localhost:5173/`.

Then, in a second terminal, create your account (registration is closed by
design, so this is the only way to make one):

```bash
make create-user
```

Sign in at **http://localhost:5173**. `make down` stops everything; your data
stays in Docker volumes until you remove them.

The defaults in `.env` work as they are on your own computer. To use Claude
(the assistant, maths transcription, question generation, marking), add your
Anthropic API key to `.env` as `ANTHROPIC_API_KEY=...` and run `make dev`
again. Without it everything else works, and AI features say they are not
set up. Spending is capped at £10 a month and £2 a day
(`backend/config/ai.yaml`); the AI usage page shows where it went.

Optional extras:

- **Push reminders:** `make vapid-keys` writes Web Push keys into `.env`.
  On a phone, push needs HTTPS, so it comes with deployment.
- **PowerPoint equations:** slides with Office equation objects need
  LibreOffice (about 500 MB more): `WITH_LIBREOFFICE=true make dev`.

## Deploying

[docs/deployment.md](docs/deployment.md) walks through putting it on a small
server with a domain name: HTTPS certificates are automatic, files can live
in a private Cloudflare R2 or Backblaze B2 bucket, and the database is backed
up daily. In short, on the server:

```bash
cp .env.example .env    # set DOMAIN, strong passwords, APP_ENV=production
make prod-up
make prod-create-user
```

## Environment variables

All are documented in [.env.example](.env.example). `.env` is git-ignored:
never commit it. Keep `ANTHROPIC_API_KEY` in `.env` only; if it is exported
in your shell, Claude Code bills that key instead of your Pro plan.

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | `development`, `test` or `production` (production hides API docs and sends HSTS) |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | The database Docker creates |
| `DATABASE_URL` | Async SQLAlchemy URL, for running the API outside Docker |
| `REDIS_URL` | Job queue and rate limits |
| `ANTHROPIC_API_KEY` | Claude API key (optional, see above) |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` | Web Push (`make vapid-keys`) |
| `STORAGE_BACKEND` | `local` (disk) or `s3` (a private bucket) |
| `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | The bucket, when `STORAGE_BACKEND=s3` |
| `DOMAIN` | Production only: your site's name |
| `BACKUP_KEEP_DAYS` | Production only: how long daily database dumps are kept |

Tunable numbers (limits, weights, model choices, prices) are not environment
variables: they live in `backend/config/*.yaml`, validated on startup
([ADR 4](docs/adr/0004-validated-yaml-configuration.md)).

## Commands

```bash
make help              # everything below, and more
make dev               # start the development stack (Ctrl+C or `make down` to stop)
make create-user       # your account
make migrate           # apply database migrations (the API also does this on start)
make test              # backend and frontend tests
make check             # lint + typecheck + tests (what CI runs)
make api-client        # regenerate the frontend's API types after changing an endpoint
make runtimes          # download the pinned Python and R runtimes by hand
```

Database tests need PostgreSQL with pgvector: they start one with
Testcontainers when Docker is running, or use `TEST_DATABASE_URL`. Without
either they skip locally; in CI a skip fails the build. Running tools on the
host needs Python 3.12 with [uv](https://docs.astral.sh/uv/) and Node 22 with
pnpm (`corepack enable`).

**Quality checks against the real Claude API** (each prints its estimated
cost and needs `ARGS=--yes` to spend it; automated tests never call the API):
`make eval-chat` (cited answers, about £0.30), `make eval-practice` (question
generation and marking, about £0.20) and `make eval-content` (grounding,
duplicates and hint leaks, about £0.15). `make eval-search` scores search on
your own golden set in `samples/golden.yaml` (local, free). `make perf`
checks response times on a seeded heavy year of use.

To check extraction on your own lecture files, put a few in `samples/`
(git-ignored: university copyright, and this repository is public), then
`cd backend && uv run pytest -m samples -s`.

## Layout

```
backend/    FastAPI API, Arq worker and scheduler (Python 3.12, uv)
  app/        api/v1/ (routes) → services/ (rules) → repositories/ (user-scoped
              data) → models/; ingestion, retrieval, ai, learning, planner,
              coding, export, storage
  config/     every tunable number, validated at startup
  migrations/ Alembic
  scripts/    create_user, evaluations, perf, reindex
  tests/      unit/, api/, db/, sim/
frontend/   React + TypeScript (Vite, pnpm, TanStack Router and Query, Tailwind)
  scripts/    fetch-runtimes.sh (pinned Pyodide and WebR)
infra/      docker-compose.yml (development), docker-compose.prod.yml,
            Caddyfile, Dockerfiles
docs/       specification, architecture, decisions and guides
```

## Documentation

- [docs/SPEC.md](docs/SPEC.md): what was asked for
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): the approved design
- [docs/adr/](docs/adr/): every decision made along the way
- [docs/deployment.md](docs/deployment.md): running it on a server, backups and restores
- [docs/security.md](docs/security.md): the security model and audit
- [docs/api.md](docs/api.md): API conventions
- [docs/database.md](docs/database.md): the tables and what owns what
- [docs/algorithms.md](docs/algorithms.md): every formula (scheduling, mastery, planning, analytics)
