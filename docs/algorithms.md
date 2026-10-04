# Adaptive learning: the formulas

Everything below is computed from stored facts: marked answers and flashcard
reviews. Every number is set in `backend/config/learning.yaml`. The code is in
`backend/app/learning/`. These formulas come from ARCHITECTURE.md section 10.

## Topic strength (`maths.py`, `mastery.py`)

Each marked answer *i* has:

- a score *s* in [0, 1];
- a difficulty weight *d* (easy 0.6, medium 1.0, hard 1.4, exam 1.7);
- an age in days.

Older answers fade with half-life *h* = 21 days:

```latex
w_i = d_i \cdot 2^{-\mathrm{age}_i / h} \quad (\times 0.5 \text{ if Claude marked it with low confidence})
```

Accuracy is pulled towards a prior *p₀* = 0.5 with weight *α* = 2, so one
right answer never reads as 100%:

```latex
\hat{p} = \frac{\sum_i w_i s_i + \alpha p_0}{\sum_i w_i + \alpha}
```

Where the topic has reviewed flashcards, their mean FSRS retrievability *R̄*
is blended in with *λ* = 0.7:

```latex
\text{strength} = \lambda \hat{p} + (1 - \lambda) \bar{R}
```

How strength is shown:

- The UI shows it with its evidence, e.g. "est. 72% · 14 attempts · last
  practised 6 days ago".
- It adds "low data" while the total weight Σ*w* is under 5.
- A parent topic shows the weighted mean of itself and its subtopics,
  weighted by each one's Σ*w*.
- Questions with no topic are scored as a module's "no topic" bucket.

## Difficulty (Elo-style)

Each topic has an ability *θ* (starting at 1500). Each question has a rating
*b*, starting from its difficulty label: easy 1350, medium 1500, hard 1650,
exam 1800.

```latex
P(\text{correct}) = \frac{1}{1 + 10^{(b - \theta)/400}}
\qquad
\theta \mathrel{+}= K_a (s - P), \quad b \mathrel{-}= K_q (s - P)
```

*K_a* = 32 and *K_q* = 16; both are halved for a low-confidence AI mark.

**Replay rule:**

- Strength, *θ* and every *b* are recomputed by replaying all of a module's
  marked answers in time order, after every marking, override, dispute,
  flashcard review or question edit.
- So they are always reproducible, and a corrected mark corrects everything
  downstream.

## Spaced repetition (FSRS, `scheduling.py`)

Flashcards are scheduled by FSRS (the `fsrs` library) at a target retention
of 0.90:

- Again, Hard, Good and Easy are ratings 1-4.
- New and lapsed cards go through short steps (1 and 10 minutes, then 10
  minutes) before FSRS intervals take over. Intervals are fuzzed slightly.
- Each review is stored as a fact (`flashcard_reviews`).
- At most 20 new cards are introduced per day.
- Before an exam, every card in its topics is seen at least once in the
  final 14 days. This applies from Phase 8, when exams exist.

## Daily quiz (`daily.py`)

Each topic of the current year's active modules gets a priority from five
terms, each in [0, 1]:

```latex
\text{priority} = w_1 (1 - \text{strength}) + w_2\,\text{overdue} + w_3\,\text{urgency} + w_4\,\text{recurring} + w_5\,\text{gap}
```

The weights are 1.0, 0.6, 1.0, 0.8 and 0.5. The terms:

- **overdue** rises from 0 just after practice to 1 at 7 days (or if never
  practised);
- **urgency** is exam proximity, 1 / (1 + days to the topic's next exam / 10),
  and 0 for a topic with no exam;
- **recurring** is 1 if the topic has a recurring mistake;
- **gap** is 1 − min(1, answers / 3).

How the quiz is built:

1. **Length:** the minutes the planner keeps for the quiz (15% of the day's
   availability, 5-20 minutes; default 15) divided by your median time
   per question (default 90 s), clamped to 5-20 questions.
2. **Allocation:**
   - questions are shared out in proportion to priority (largest-remainder
     rounding);
   - each module first gets at least 1 question, in its highest-priority
     topic;
   - no topic gets more questions than it has available;
   - questions answered right in the last 2 days are skipped.
   - With no data every term is equal, so the first quizzes spread evenly.
3. **Choice within a topic:**
   - up to 2 questions per quiz are aimed at a recurring mistake (questions
     previously got wrong in that way);
   - the rest are those whose predicted success *P* is nearest the
     **65-80%** band.
4. **Order:** topics are interleaved, and the same question type is avoided
   twice in a row.

**Top-up:**

- If a high-priority topic has fewer than 3 questions, starting the daily
  quiz asks Claude for 4 more, from your materials.
- They pass the same checks as any generated question, and are saved without
  a preview (SPEC 40 allows this for quiz questions).
- At most 2 topics a day are topped up.
- There is no top-up once the AI budget warning has been reached.

## Mistake bank (`mistakes.py`)

A wrong answer can carry a mistake category, as Claude classified it when it
explained the answer:

| Category | Example |
| --- | --- |
| Arithmetic or algebra slip | √36 carried as 36 |
| Sign error | multiplying by 4 − i instead of 4 + i |
| Wrong method | `linspace` treated as a colon range |
| Concept confusion | a loop accumulator and its index merged into one variable |
| Incomplete justification | an assertion with no reason given |
| Instance instead of general | proved for one case, not in general |
| Notation | −√−1 written for −i |

How mistakes are grouped:

- Mistakes are grouped by topic and category.
- A group is **recurring** at 3 or more within 30 days.
- Within a group, descriptions with embedding similarity of 0.9 or more are
  shown as one pattern with a count.

## Learning profile (`profile.py`)

Measured statistics only. There are no personality claims (SPEC 28):

- accuracy by question type;
- accuracy under exam conditions versus untimed;
- the categories of the last 20 mistakes;
- hints per answer;
- the flashcard recall rate over 30 days, and recall minus question accuracy;
- active days.

A snapshot is taken at most weekly, on the first visit, once there are at
least 10 answers. Claude then writes three to five bullet points that must
cite those numbers. Question generation receives a one-line factual hint from
the same data, e.g. "3 of the last 10 mistakes were sign errors".

## The simulated learner (`tests/sim`)

The learner has known skill in three topics: 90%, 60% and 25%. They answer two
weeks of daily quizzes; the system never sees those numbers.

Each run checks that:

- the first quiz spreads evenly;
- in the last week the weak topic gets the most practice and the strong one
  the least;
- strength ranks the topics in their true order;
- the weak topic's *predicted success* (mean P(correct) over its questions)
  is the lowest and within 0.15 of its true 25%.

Elo ability is not compared across topics: it is fitted together with each
topic's own question ratings, so only P(correct) against those questions
means anything, and a rarely practised strong topic stays near 1500. (An
earlier version of this page claimed the abilities came out in order; that
check was unsound and flaky, see ADR 13.)

In the reference run the estimated strengths were 93%, 65% and 30%.

## Revision planner (`app/planner`)

All numbers are in `config/planner.yaml`.

### Time available

For each day: an exception for that date if you set one; else 0 on a rest
day; else your weekly hours for that weekday; else the default (2 h on
weekdays, 1 h at weekends). From that the planner keeps back:

- **daily quiz:** 15% of the day, 5-20 minutes (none if you have no
  questions);
- **flashcards:** the cards due that day × 20 s, at most 30 minutes.

What is left is the day's **capacity** for planned sessions.

### Need

For each topic on an exam (all the module's topics, or the ones you chose):

```latex
\text{need} = 300 \times \frac{\text{weighting}}{100} \times (1 - \text{strength}) \times (1 + 0.5\,\text{gap}) \times (1 + 0.1\,(3 - \text{confidence}))
```

Weighting defaults to 100% and the confidence factor to 1 when not given.
Topics with no exam get light upkeep: 30 × (days in the plan / 14) ×
2 (1 − strength) minutes, at 0.3 of the priority.

Both are then multiplied by the topic's **importance** factor,
1 + 0.15 (importance − 3), from the importance (1-5, default 3) you set in
the topic tree: 0.7 for a 1, 1.3 for a 5. A topic not at 3 shows
"importance n/5" in its reasons.

### Allocation (`allocator.py`)

A pure, deterministic function, tested with Hypothesis properties.

1. One **mock exam** per exam, on the day with room nearest to 4 days before.
2. Days are filled in order. On each day, blocks (default 45 minutes, at
   least 20) go to the topic with the highest key:
   - first, any exam topic that has no time yet (so every exam topic is
     covered before any gets a second block);
   - then priority = need left / 300 × urgency × factor, where
     urgency = 1 / (1 + days to exam / 10), and the factor is 0.7 if the
     previous block was the same module (modules interleave).
3. Rules:
   - at most one block per topic a day, and at most 3 sessions a day;
   - the same topic at least 2 days apart, except in its exam's last 3 days;
   - nothing for a topic on or after its exam's day;
   - never more than the day's capacity.
4. Sessions you moved are **locked**: they stay put, use their day's
   capacity and count towards their topic's need.
5. If an exam's need can't be met, a **shortfall** is reported, not crammed:
   - "time" when there are not enough minutes before the exam;
   - "spacing" when there are minutes, but the spacing rules leave them
     unused (too few days left).

### Replanning

There is no scheduler. The plan is rebuilt when you read it and:

- it was made on an earlier day (in your time zone), or
- any topic's mastery was recomputed since (you practised).

Changing exams, availability or preferences, or moving a session, replans
at once. Rebuilding marks past planned sessions as missed, deletes future
unlocked planned ones, and keeps done, missed and locked sessions.

### "I have N minutes" (`session_builder.py`)

From the minutes you have (10-240):

1. **due flashcards**, up to 35% of the time;
2. a 10-minute **drill** on a recurring mistake, if you have one (the one whose
   topic has the nearest exam, then the most frequent);
3. the rest on the highest-priority topic today (same priority as the
   allocator), split over the top two topics above 40 minutes.

Each block's reason quotes the measurements behind it, for example
"est. 30% · 4 mistakes in 30 days · last practised 6 days ago · MATH101 exam
in 34 days". The assistant's `plan_session` tool returns the same session.

### Recommended next

"What should I study next?" (SPEC 71) uses the same ranking, best first:

1. due flashcards, if 10 or more are due;
2. then the topics with the highest priority today, each with its factors
   (strength, importance, recent mistakes, last practice, the exam) and any
   recurring mistake in it.

Today shows the top three.

### Exams and flashcards

In an exam's final 14 days, every card of that module not reviewed since the
window opened is due, so each one is seen at least once before the exam.

### Notifications (`notifications.py`)

Made when you open the app, each at most once (a dedupe key per reminder):

- an exam 14, 7 and 1 days away;
- today's quiz not done after 18:00 (your reminder hour);
- an exam topic not practised for 9 days;
- 10 or more flashcards due.

Each kind can be switched off, and none are made in your quiet hours. Read
reminders older than 30 days are deleted.
