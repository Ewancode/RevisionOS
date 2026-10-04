# 16. Coding practice: code runs in the browser; the hint ladder is the server's

Date: 2026-10-05 · Status: Accepted (Phase 10; refines ARCHITECTURE.md sections 1, 9 and 18)

## Decision

**Code never runs on the server.** Python runs in Pyodide inside a Web
Worker; R runs in WebR, which has its own worker. The server stores exercises,
the submissions your browser reports, and hints. It checks exercises without
running them: Python is *parsed* with `ast` (syntax errors in starter,
solution or tests), and every exercise needs 1-20 named tests with at least
one visible.

**Pinned runtimes from CDNs.** `coding.yaml` pins Pyodide 314.0.7
(Python 3.14, jsDelivr) and WebR 0.6.0 (webr.r-wasm.org); the browser reads
them from `/api/v1/coding/config`. Self-hosting tens of megabytes of
WebAssembly is not worth it for one user. **The SPA's Content-Security-Policy
(Phase 13) must allow** these origins for scripts, `connect-src` and workers,
plus `'wasm-unsafe-eval'`. WebR uses its PostMessage channel, so no
cross-origin isolation headers are needed.

**Tests are code run after yours.** In Python, each test runs in a copy of
your code's namespace and passes unless it raises (an `assert`); in R, each
runs in a child environment and passes unless it errors (`stopifnot`,
`stop`). The Python harness (`harness.py`) is the same file the backend's
tests run under CPython, so its marking is tested for real.

**Time limits.** Starting a runtime and downloading packages get a long
allowance (120 s); your code's run gets 15 s. Without cross-origin isolation
a run cannot be interrupted, so a runaway run stops its worker and the next
run starts a fresh one.

**Submissions are trusted, within reason.** The browser reports results; the
server only checks they name the exercise's tests in order. Tests (hidden
ones included) are sent to the browser to run, so a determined student could
read them. That is acceptable for a personal app (section 16 lists this
risk). The page shows hidden tests by number only, without their code or
messages.

**Claude's exercises are drafts, checked twice.** The server checks them
statically (with one repair round on Sonnet, like questions); then the draft
preview runs each reference solution against its own tests in your browser,
and only exercises that pass both can be saved.

**The hint ladder is enforced by the server** (section 9): a guiding
question, a hint, a stronger hint, the next step, then the full solution.

- Rungs are climbed one at a time; the server chooses the next.
- Claude writes rungs 1-4 (route `tutoring`, Sonnet) and never receives the
  reference solution, hidden tests or a question's answer key.
- Rung 5 is the stored solution, returned without an AI call, so it cannot
  leak early. It unlocks after you submit an attempt, and never for
  exercises marked as assessed coursework (section 18, academic integrity).
- The same ladder (rungs 1-4) serves questions in practice quizzes; each
  hint increments the answer's `hints_used`, which the learning profile
  already counts. The worked solution appears after submitting, as before.
- No hints of either kind while a mock exam is open (423).

**Deleted exercises go to the trash** with the other content, restorable
for 30 days.

**Checking the runtimes.** `runtime-check.html` (development only, or in a
build with `RUNTIME_CHECK=1`) runs real Python and R exercises through the
app's runners: pass, fail with the reason, packages, output, and a stopped
infinite loop. It passed on the dev server and on the production bundle.
Workers are built as ES modules (`worker.format: "es"`), since the Python
worker loads Pyodide with a dynamic `import()`.

## Consequences

- The first run of each language downloads its runtime (tens of MB), once
  per browser cache.
- MATLAB (MATH111) still cannot run; section 18's optional Octave runner
  stays after Phase 13.
- Coding submissions do not yet feed topic strength or the streak; that
  needs a scoring rule and is left for later.
