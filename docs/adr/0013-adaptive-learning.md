# 13. Adaptive learning: replayed mastery, FSRS, the daily quiz

Date: 2026-10-03 · Status: Accepted (refines ARCHITECTURE.md section 10)

## Decision

The formulas are the design's (section 10); `docs/algorithms.md` states them
with the configured numbers. These implementation choices were made along
the way.

**Mastery and difficulty are replayed, not updated in place.** After any
change that affects them (marking, override, dispute, flashcard review, a
question's topic or difficulty changing), a module's topic strengths, Elo
abilities and question ratings are recomputed by replaying all its marked
answers in time order:

- `topic_mastery` is a derived cache.
- Question ratings are reset to their label's starting value before the
  replay.
- A corrected mark therefore corrects everything after it.
- A formula change takes effect on the next recompute, with no migration.

For one student this takes milliseconds.

**FSRS from the `fsrs` library** (v6, typed). The card's state lives in
columns on `flashcards`, and each review is an append-only `flashcard_reviews`
row. Learning steps, the maximum interval, fuzzing and the new-cards-per-day
limit are in `learning.yaml`.

**The daily quiz.**

- It spans the current year's active modules, so `quizzes.module_id` is
  nullable, and a new quiz kind `daily` was added.
- There is one quiz per day: starting again returns the open one.
- Urgency (exams) is in the formula with weight 1.0 but is 0 until Phase 8
  adds exams.
- "Available time" is a minutes parameter (default 15) until Phase 8 adds
  availability.

**Top-up, saved without preview.** The design says Claude generates a
question "when the bank lacks a question at the needed difficulty". The
implementation:

- When the daily quiz starts, high-priority topics with fewer than 3 questions
  get 4 generated in the worker.
- These are checked as usual, and the valid ones are auto-saved (SPEC 40
  allows that for quiz questions).
- At most 2 topics a day, and none once the budget warning (75%) is reached.
- Today's quiz uses what exists; the new questions serve later quizzes.

**The learning profile has no cron job.** The design mentions a scheduler
process for weekly jobs. Instead:

- A snapshot is taken lazily, on the first profile visit each week, once
  there are at least 10 answers.
- Claude's summary is written in the worker (`learning_profile` route, Haiku,
  prompt `learning_profile.v1`). It must cite the measured numbers and make
  no personality claims.
- The scheduler process arrives with the first job that must run on time,
  such as Phase 8 notifications.

**Mistake patterns.** Mistakes are grouped by (topic, category). Descriptions
within a group are merged by embedding similarity using the local embedding
model, with no AI cost.

**The assistant gains `get_progress`.** It is a read tool returning:

- the weakest topics, with their evidence;
- cards due;
- recurring mistakes;
- what today's quiz would cover.

The assistant can therefore answer "how am I doing?" from data.

**A test clock.** `app.core.clock.freeze()` lets tests move through days;
production always reads the real clock.

## Evidence

- Hypothesis property tests: strength stays in [0, 1] and never falls when a
  score rises; weights decay with age and grow with difficulty; Elo is
  symmetric; allocation respects capacity, the module floor and the total.
- FSRS tests: intervals grow after Good, a lapse after Again, previews are
  ordered, and recall fades.
- **Simulated learner** (the phase's acceptance test). Hidden skill of 90%,
  60% and 25% over 14 daily quizzes:
  - the first quiz spread 4/3/3;
  - by the last week the weak topic got most of each quiz (8-12 of 15);
  - estimated strengths were 93%, 65% and 30%, and Elo abilities 1681, 1515
    and 1327, both in the true order.

## Consequences

- Recomputing a module costs one query per table: fine for one student's
  history, but at scale it would need incremental updates.
- Exam proximity, availability and the exam-window card cap are wired in
  and wait for Phase 8.
