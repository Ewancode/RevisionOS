# 18. Hardening: rate limits, push allow-list, trash purge, performance

Date: 2026-10-05 · Status: Accepted (Phase 12; refines ARCHITECTURE.md sections 12-13 and ADRs 14, 16, 17)

## Decision

**Security changes** (details and severities in
[security-audit.md](../security-audit.md)):

- **Per-account rate limits** on every route that calls Claude, uploads or
  sends a test push (`rate_limited(scope)` in `app/api/deps.py`; numbers in
  `platform.yaml`). They sit alongside the budget guard: the guard caps
  money, and the limits cap bursts. A route-table test makes the limit part
  of the definition of an AI route.
- **Push endpoints must be on an allow-listed push service**
  (`planner.yaml` `push_hosts`), checked on subscribe and again before
  every send.
- **The trash is emptied after 30 days** by a second scheduler cron
  (`empty_trash`, `app/trash.py`).

**Performance targets** (set before measuring; `platform.yaml`
`performance`): p95 300 ms for anything a page needs, 600 ms for
whole-history views, 800 ms for search, measured in the server process.
With 8 clients at once for 20 s, there must be no errors and p95 must
stay under 900 ms. `make perf` seeds a separate `revision_os_perf` database
with a heavy year (8 modules, 6,000 pages, 12,000 chunks, tens of thousands
of answers and reviews) and checks every target.

**What it took to meet them:**

- **Select columns, not entities,** where a request reads thousands of
  rows: the mistake bank, the learning profile and the daily-quiz
  candidates. Loading ORM entities was most of the time (mistakes went from
  489 to 62 ms).
- **Count in SQL:** the daily quiz's availability counts and
  "recently right" are subqueries, not Python loops (626 to 84 ms).
- **Window the analytics.** Each view loads only the events it shows (7
  days for the overview, 12 weeks for trends, 14 days for readiness).
  Active days are computed in SQL as distinct local dates. The streak
  still sees the whole history.
- **Defer embedding columns** on questions and chunks. They are only read
  by vector search, which selects them explicitly.
- **Freeze the start-up heap** (`gc.freeze()` after the embedder loads, in
  the API, worker and harness). The embedding model's millions of objects
  made each full collection a 100 ms+ pause, which tripled tail latency
  under load.
- **Never let fsrs sleep.** `fsrs.Card()` without a `card_id` sleeps 1 ms
  to make one up, blocking the event loop for every card. Cards are built
  with an id derived from the flashcard's UUID, and a test guards this.

Results on this machine (Docker on Windows, 2026-10-05): every page
endpoint has p95 ≤ 113 ms, history views ≤ 119 ms and search ≤ 161 ms. The
burst served 709 requests with p95 430 ms and no errors.

**The tutor prompt is now `tutor_hint.v4`.** The Phase 12 content evaluation
found hints on multiple-choice questions that matched the key idea to an
option. v2 stopped rung 3 from laying out a whole plan for one-step
problems. v3 limited rung 2 to naming the method. v4 stops the tutor
mentioning or evaluating options at rungs 1-3. With v4, no hint stated the
answer (0 of 30, two runs).

**Questions that print their own answer are rejected** by validation (an
expression or short answer of 5+ characters found in the stem). The
evaluation caught one.

## Consequences

- A burst of legitimate AI use above 60 requests in 10 minutes gets a
  429. That's far above one person's pace; the number is in config.
- Self-hosted push services (other than the four big ones) won't work
  until added to `push_hosts`.
- `make perf` is a manual check: it takes a few minutes and needs the
  embedding model, so it is not in CI.
- Hints on one-step questions can still leave only that step after rung 1
  or 2 (naming the fact *is* the step). The evaluation reports these for
  review but doesn't fail on them.
