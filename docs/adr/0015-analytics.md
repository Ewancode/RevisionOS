# 15. Analytics: a basis on every figure, measured study time, SVG charts

Date: 2026-10-04 · Status: Accepted (Phase 9; refines ARCHITECTURE.md sections 1 and 15)

## Decision

**Every figure carries its basis.** The analytics API returns numbers as
`{value, basis}`, where the basis is a sentence naming the stored rows it was
computed from ("Mean mark of 20 answers marked in the last 7 days (partial
credit counts)"). The UI shows it beside each figure (ⓘ) and in its tooltip.
Missing data is `null` and shows as "–", never as 0. This is how the phase's
criterion, "every number on screen traces to stored data", is met and
tested.

**Computation is pure.** `app/analytics/compute.py` takes plain records
(answers, reviews, sessions) and returns figures; the service only loads the
rows. Properties (streaks, caps, weekly totals, readiness as a weighted
mean) are tested with Hypothesis, and an API test seeds a fully known history
and checks each dashboard number against a value worked out by hand.

**Study time is measured.** There is no session timer, so study time is the
recorded time of marked answers and flashcard reviews, each capped (15 min,
120 s) so an abandoned tab does not count as hours. Untimed items add
nothing and the basis says how many there were. Planned sessions marked
done are *not* added, since the practice inside them is already counted.

**Readiness is a weighted summary, not a prediction.** Five measured
components (coverage, strength, recent marks, mock exams, recency). Missing
components are left out and the weights rescaled, rather than counted as 0.
The card always says it is not a predicted mark.

**Readiness, the module dashboard and the planner share one view of the
data.** Both load the planner's context (exams, topic strengths, recency), so
"exam topics", "strength" and "last practised" mean the same everywhere.

**Charts are small SVG components, not Recharts.** Section 1 named Recharts.
The charts needed are a few bars, a line and a day grid. Hand-written SVG
keeps the bundle smaller, renders in jsdom (Recharts' responsive container
draws nothing there), and lets each chart carry an accessible name, a basis
caption and its numbers as a screen-reader table. If richer charts are
needed later, Recharts can still be added.

**What the dashboard shows is not chosen by Claude yet.** SPEC 4 asks Claude
to decide what is most useful; section 18's default is to rank widgets by the
recommendation engine. Phase 9 shows a fixed set (at a glance, recommended
next, today's revision, upcoming exams, the daily quiz and so on). Ranking
them is left for Phase 11 (polish), where the layout work happens.

## Consequences

- Opening a dashboard costs no API calls; each request reads one user's
  rows and computes in milliseconds.
- If timing is not recorded (older answers), study time undercounts, and
  says so.
- Adding a figure means writing its basis, which keeps new numbers
  traceable.
