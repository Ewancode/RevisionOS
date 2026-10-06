# 19. Export and restore, S3 storage, deployment, self-hosted runtimes

Date: 2026-10-06 · Status: Accepted (Phase 13; refines ARCHITECTURE.md sections 6, 12 and 15, and ADRs 16 and 18)

## Decision

**One export, everything in it** (SPEC 50). Settings > Your data builds a ZIP
in the worker (`app/export/`):

- `data/<table>.jsonl`: every row of every table you own, one JSON object per
  line, each value encoded by its column type (vectors as base64 float32,
  bytes as hex). This is what restore reads.
- `files/`: your uploads, page images and answer photos.
- For people and other apps: `csv/` (questions, flashcards, every answer,
  quizzes, reviews, study sessions, exams, topic progress, coding
  submissions), `markdown/` (materials, lecture text, questions, flashcards,
  coding exercises and conversations, per module), and `anki/revision-os.apkg`
  (a deck per module, MathJax maths, note ids from card ids so re-importing
  updates rather than duplicates). Items in the trash are only in `data/`.

The tables are chosen from the SQLAlchemy metadata, not a hand-kept list:
everything with a `user_id` (or under a parent that has one) except sign-in
sessions, the audit log, push devices, export jobs and pending deletions. A
test fills every exported table and checks a full round trip, so a new table
is covered or the test fails. Embeddings are included, so a restore is exact
and needs no re-indexing (unless the embedding model differs, when the
documents are re-indexed after the restore). Exports are kept for 7 days.

**Restore goes into an empty account** (no academic years). It is
all-or-nothing in one transaction. Every row gets a new id and your user id;
ids inside text and JSON (storage keys, links, citations) are rewritten too.
A reference to anything not in the archive, a value of the wrong type, an
unsafe path, a zip bomb or an archive from a newer schema stops it before
anything is kept. Settings, availability, notifications, the plan and weekly
profiles replace the account's own; everything else is added. Older archives
restore: columns are matched by name and new ones take their defaults.

**An S3-compatible storage backend** (`app/storage/s3.py`; R2, B2 or S3),
chosen with `STORAGE_BACKEND=s3`. The storage interface's `local_path` became
`local_copy`, a context manager: a remote backend downloads to a temporary
file and removes it afterwards. Both backends pass the same contract test
(S3 against moto). Files are still streamed through the API after an
ownership check; pre-signed URLs were not needed at this size.

**Deployment is one server running `infra/docker-compose.prod.yml`:**
Caddy (automatic HTTPS, the built app, security headers) in front of the API,
worker, scheduler, PostgreSQL and Redis, plus a `backup` service that dumps
the database daily. Only Caddy is exposed. The API trusts Caddy's forwarded
client address and scheme (`--proxy-headers`), so rate limits see real
addresses and cookies stay Secure. Managed hosting is possible but not
needed: a 4 GB server covers it for a few pounds a month
([deployment.md](../deployment.md)).

**The Python and R runtimes are served from the app's own origin** (the
Phase 12 audit's finding 4). `frontend/scripts/fetch-runtimes.sh` downloads
them when the web image is built (and when the dev stack starts) and checks
SHA-256 checksums before installing anything:

- Pyodide: the release's core archive, byte-identical to its CDN. Packages
  still come from Pyodide's CDN (`packageBaseUrl`), but Pyodide checks each
  against the SHA-256 in the self-hosted lock file, so they can't be swapped.
- WebR: its GitHub release archive is a different build from the one its site
  serves (it reports itself as `0.5.10-dev`), so the site's 115 files are
  pinned one by one (`frontend/scripts/webr-0.6.0.sha256`). The site serves
  `R.wasm` gzip-encoded; the script stores it decoded. R packages come from
  the WebR repository, unverified (an accepted risk, [security.md](../security.md)).

`coding.yaml` now names a same-origin `base_url` and a separate
`package_url` per runtime; a test checks the versions match the script.

**A strict Content-Security-Policy on every page** (finding 5): scripts only
from the origin, no `eval`, no inline scripts, no framing, and network access
only to the origin and the two package sources. WebR links R's libraries
with `eval`, and a worker takes its CSP from its own script's response, so
`/runtimes/webr/*` alone gets a policy that allows `eval`. A test keeps the
CSP in step with `coding.yaml`.

**`docs/database.md` is generated from the models** (`make db-docs`), with a
test that fails when it is stale, like the API client.

## Consequences

- An export is a complete, portable backup that you hold yourself; it does
  not replace the server's daily database dumps, which are faster to restore.
- Restoring into an account that already has data is refused. Merging two
  accounts is not supported.
- Upgrading a runtime means updating the version and checksums in
  `fetch-runtimes.sh` (and, for WebR, regenerating the manifest from the new
  version's files) and the URL in `coding.yaml`; the tests catch a mismatch.
- The first start of the dev stack downloads about 60 MB of runtimes;
  `public/runtimes/` is git-ignored. Vite's static server labels `.gz` files
  as gzip-encoded, which breaks WebR's filesystem images, so a small dev-only
  middleware serves them as plain bytes (`vite.config.ts`), as Caddy does.
- Versioned runtime files are cached by browsers as immutable: a version's
  files must never change once served. A new version gets a new path.
- The sidebar can be resized by dragging its edge (also from the keyboard);
  the width is remembered per browser. A UI preference, not a design change,
  noted here because it touched the app shell.
