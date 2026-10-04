# 14. Revision planner: lazy replanning, coverage first, reminders on read

Date: 2026-10-04 · Status: Accepted (refines ARCHITECTURE.md section 11)

## Decision

The planner follows section 11: a pure, deterministic allocator, sessions
with reasons, "I have N minutes", and availability you can describe in
words. The formulas and numbers are in `docs/algorithms.md`; these are the
choices made while building it.

**Replanning is lazy; there is no cron.** The plan is rebuilt when it is
read and either it was made on an earlier local day or a topic's mastery
was recomputed after it. Anything you change (exams, availability,
preferences, moving a session) replans at once. With one user, rebuilding
takes milliseconds, so a scheduler would add a moving part for nothing.

**Reminders are made on read.** Notifications are created when you open the
app, each with a dedupe key (for example `exam:<id>:7`), and inserted with
`ON CONFLICT DO NOTHING`, so a reminder appears once however often you look.
Quiet hours and per-kind switches are respected. Push notifications wait for
the PWA in Phase 11; until then the bell in the sidebar is the only channel.

**Exam coverage comes first outright.** The first version gave uncovered exam
topics a priority boost (`uncovered_boost`). A property test found plans
where a heavily weighted topic still took a second block before a light one
got any. Coverage is now the first part of the sort key, ahead of priority:
every exam topic gets time before any gets a second block, whenever capacity
allows. `uncovered_boost` was removed from `planner.yaml`.

**A shortfall says why.** It is reported as `time` (not enough minutes before
the exam) or `spacing` (minutes left, but the spacing rules leave them
unused). Without this, a plan with free time showed "not enough time", which
was misleading.

**Moved sessions are locked.** Moving a session fixes it to that day; replans
keep it, count its minutes towards the topic's need, and rebalance the rest.
Done, missed and locked sessions are never deleted by a replan; past planned
sessions become missed.

**Availability in words is a proposal.** Claude (Haiku, structured output)
turns the text into weekly minutes and dated exceptions. Nothing is saved
until you confirm; dates in the past are dropped.

**The planner feeds the adaptive features.** The daily quiz's urgency term
and its length come from the planner (exam proximity, and 15% of the day's
availability). In an exam's final 14 days every card of that module not
reviewed since the window opened is due.

**Topic importance counts.** The importance (1-5) set in the topic tree
multiplies a topic's need by 1 + 0.15 (importance − 3), as SPEC 71 asks.
The design's demand formula (section 11) did not mention it.

**Recommendations are deterministic.** "Recommended next" is the planner's
ranking with its factors, not a Claude call; the assistant phrases the same
numbers when asked (through `plan_session`).

**`StudySessionOut`.** The planner's session schema is named
`StudySessionOut` so that it does not collide with the auth `SessionOut` in
the generated API client.

## Evidence

- Allocator tests (`tests/unit/test_allocator.py`, six Hypothesis
  properties and one example): plans never exceed a day's capacity or
  session limit (locked sessions may exceed the count only by themselves);
  spacing holds and nothing lands on or after an exam; the same inputs give
  the same plan; every exam topic gets time when there is room; a shortfall
  is reported instead of cramming; at most one mock per exam, before it; and
  weak topics near their exam come first.
- API tests: plans favour weak topics, mock exams land 4 days before,
  moving locks and rebalances, missed sessions, shortfalls, rest days and
  exceptions, the plain-English proposal, "I have 45 minutes" with explained
  blocks, the assistant's `plan_session`, notifications (once, read, quiet
  hours, switches), daily-quiz urgency and the exam-window card rule.
- Access-control attacks were added for exams, sessions, notifications and
  availability exceptions; reading another user's notification or deleting
  another user's exception returns 404.

## Consequences

- A plan can be up to a page-load stale (until you open the app).
- Reminders are not delivered while the app is closed until Phase 11.
- Allocation is greedy, not optimal; it is simple to explain, and the
  property tests pin down what it guarantees.
