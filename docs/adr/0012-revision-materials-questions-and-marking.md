# 12. Revision materials, generated questions and marking

Date: 2026-10-02 · Status: Accepted (refines ARCHITECTURE.md sections 5, 9 and 10)

## Decision

**Everything generated is a draft first.** Generation runs in the worker and
writes a `drafts` row: a material, a set of questions, or a set of
flashcards. You preview it, then save, edit, regenerate (optionally with new
instructions) or discard it (SPEC 40). Drafts are kept until you decide, so
nothing generated is lost. The assistant can start one (`start_draft`, a
"draft"-risk tool); the conversation links to it.

**Generation is grounded in your materials.**

- If you chose files, Claude gets their pages.
- If you named a topic or gave instructions, Claude gets the best search
  results for them.
- If you asked for "questions on this module", or the search finds little,
  Claude gets a random sample of pages from across the module, with
  university material first. Searching on the module's title found almost
  nothing, so a module-wide request needs pages from the whole course.

**Materials keep citations; questions record their sources.**

- Materials are Markdown with the same verified citations as assistant
  answers.
- Questions and flashcards come back as JSON matched to a schema (structured
  outputs), which the API cannot combine with citations. So passages are
  numbered, each item lists the ones it used, and the server checks those
  numbers before saving the pages as the item's sources.

**Generated questions are checked, never trusted**
(`app/practice/validation.py`):

- the shape is right for the question type;
- multiple choice has 2-6 distinct options and exactly one correct;
- numerical answers are recomputed from a SymPy check expression that Claude
  must supply;
- algebraic answers parse, using only their declared variables;
- rubrics give every point positive marks;
- model answers are written out in full;
- `$` delimiters balance;
- every cited passage was supplied, and every item cites at least one;
- near-duplicates of the bank (cosine similarity 0.93 or more, on local
  embeddings) are rejected.

Items that fail get one repair attempt on the route's stronger model (Haiku
to Sonnet, or Sonnet to Opus). Items that still fail are shown with their
problems and cannot be saved. Questions are checked again when you save them.

**Safe maths.** SymPy's parser evaluates Python, so input is tokenised first.
Only numbers, operators, brackets, an allow-list of functions and constants,
and the question's declared variables reach it. Calculus (`integrate`,
`diff`) is allowed only in Claude's check expressions, never in student
answers. Algebraic answers are compared numerically at random points, which
is more robust than `simplify`.

**Marking by answer type** (section 10's table):

- Exact match: multiple choice and true/false.
- Tolerance with units: numerical answers.
- SymPy equivalence: algebraic answers.
- An accepted wording, otherwise Claude's cheap marking route: short answers.
- Claude against a rubric: explanations and derivations.

Rule marks appear as soon as you submit. In the worker, Claude then marks the
rest, re-marking once on the stronger model when its confidence is low. One
call explains every wrong rule-marked answer, in the five parts SPEC 25 asks
for. Each wrong answer also gets a mistake category from `learning.yaml`, so
the Phase 7 mistake bank has history from day one.

- Disputing a Claude mark re-marks it on the stronger model.
- You can override any mark; the original is kept.
- If Claude is unavailable, those answers stay unmarked for you to mark, and
  nothing else fails.

**Exam mode is enforced by the server.**

- A mock exam has a deadline, with a grace period set in `practice.yaml`.
- Late answers are refused, and an expired exam is submitted automatically
  the next time anything touches it.
- While an exam is open, the assistant, generation, disputes and new quizzes
  are refused (423).
- Photo transcription of your own working still works, because it is marking
  input, not help.

**Photos of working.**

- A photo is validated as an image and re-encoded, as uploads are.
- It is stored under an allow-listed key and transcribed by the
  maths-transcription route.
- You check the transcription and edit it into your answer before it is
  marked.

**Versions.** A material's versions are never edited:

- editing, restoring an old version or accepting Claude's improvement each
  add a new version;
- deleting a version is permanent and asks first, and the current version
  cannot be deleted;
- diffs are line-based.

**Deleting things.**

- Materials and flashcards go to the 30-day trash.
- Questions are retired rather than deleted, so your attempts keep their
  meaning.
- The Elo rating column is filled from the difficulty label now; Phase 7
  recalibrates it from real outcomes.

Tunable numbers are in `config/practice.yaml`. The question ratings are in
`learning.yaml`.

## Not in this phase

- **Phase 7:** spaced-repetition scheduling of flashcards (FSRS), the
  adaptive daily quiz, mastery, and the mistake bank's recurring-pattern
  view.
- **Phase 10:** coding questions.
- **Later:** images on flashcards, and automatic analysis of new uploads
  (SPEC 30).

## Evidence

`make eval-practice ARGS=--yes` generates questions from MATH101 through the
real API, then marks two attempts at them: one with the correct answers and
one with wrong answers.

The final run:

- 11 of 11 questions were valid: 10 first time, 1 after the repair round.
- Every answer type marked right answers as right (1.0) and wrong answers as
  wrong (0.0).
- It cost £0.19.

Two earlier runs found real problems, which are now fixed and covered by
tests:

1. The API rejects an enum declared on a `["string", "null"]` type. Nullable
   values are now written as `anyOf`, and a unit test checks every schema.
2. A generated "model answer" read only "See solution above." The marker
   rightly gave it 0. The prompt (`generate_questions.v2`) and validation now
   require a model answer written out in full.
