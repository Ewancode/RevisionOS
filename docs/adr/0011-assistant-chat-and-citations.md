# 11. The assistant: retrieval, citations and the agent loop

Date: 2026-10-02 · Status: Accepted (refines ARCHITECTURE.md sections 7, 8 and 9)

## Decision

**Retrieval before the first call, then Claude searches.** Each message is
searched as typed: in the conversation's scope (module or topic, widening
when thin), with no model call. The best passages go to Claude with the
question. Claude can then call `search_materials` with its own query. That
replaces the separate Haiku "rewrite follow-ups" step in section 7. For "what
about the second one?", Claude writes the standalone query itself, inside a
call it is already making. When nothing clears the relevance floor, the
message tells Claude so plainly (SPEC section 68).

**Native citations on `search_result` blocks.** Section 8 planned a benchmark
of the API's native citations against our own passage-ID format. I chose the
native citations and dropped the passage-ID format without running that
benchmark, for three reasons:

- Each passage is sent as a `search_result` block with a source id
  (`doc:<id>#page=<n>`) and a title (file and page).
- Each returned citation names the block it points at, by position. The
  server keeps every citation whose position and source id match a passage it
  actually sent in this turn, and drops and logs the rest. That is the
  deterministic check section 7 requires, without parsing ids out of Claude's
  prose.
- The passage-ID format would have needed its own parser and prompt rules.

The evaluation below shows the native citations meet the bar.

**Provenance.** The University / My notes / General knowledge badge is
computed from the verified citations. An answer with none is badged "General
knowledge — not from your materials".

**Read tools only, plus delete requests.** The tools are `search_materials`,
`read_page` (a whole page, also citable) and `list_materials`.
`request_delete_document`, `request_delete_topic` and `request_delete_module`
create a `pending_actions` row with a server-built preview and a 10-minute
expiry. Only `POST /pending-actions/{id}/confirm`, sent from the signed-in
browser with a CSRF token, carries one out: it is the ordinary soft delete,
recorded in the audit log. Section 5 lists a `token_hash` column for pending
actions. I left it out: the confirm request is already tied to the owner,
checked against CSRF, single-use (by status) and time-limited, and no tool can
reach it.

**The loop.** The loop has a limit of `chat.max_model_calls` API calls
(4). The last call is sent with `tool_choice: none`, so Claude must answer
with what it has. Each call is checked against the budget for its worst-case
cost before it is sent. Every call records its usage, including refused,
truncated and stopped ones; the tools it asked for go in
`ai_interactions.tool_calls`.

**Streaming over POST.** `POST /conversations/{id}/messages` returns
server-sent events: `status`, `delta`, `action`, `done` and `error`. The
browser reads the response body itself, because `EventSource` cannot POST or
send the CSRF header. A Redis lock allows one answer at a time per
conversation. Stopping an answer, or losing the connection, saves the text
shown so far as "stopped" and records the tokens already billed.

**History is resent as plain text.** Earlier turns go back as text. Their
citation markers, passages and tool calls are not resent, which keeps
follow-up questions cheap; Claude searches again when it needs to. Thinking
blocks are echoed unchanged within one answer's loop, as the API requires,
and are not resent across turns.

**Caching.** There are two cache breakpoints: one after the tools and system
prompt (the same for every conversation) and one after the newest message.
Each further call in the loop therefore reads the whole prefix from the
cache.

**Routing.** The new `chat` route uses Sonnet 5.5 at medium effort, with the
server-side refusal fallback. A refused answer is discarded, not shown as
complete.

**Conversations are deleted permanently.** They are not course material, and
the UI asks for confirmation first.

**Usage dashboard.** `GET /ai/usage?days=` returns requests, tokens and
estimated cost by feature, model, module and day, plus the number of calls
the budget blocked. Days are counted in the budget's timezone.

## Not in this phase

- Confirmation before large jobs (`budget.confirm_above_tokens`) arrives with
  the first large job, bulk generation in Phase 6. An answer is capped by its
  route's `max_tokens` and by the loop limit.
- The tutor hint ladder and the Exam Mode lock need questions and attempts
  (Phases 6 and 7).
- The learning-profile summary in the prompt arrives in Phase 7.
- Write tools (`create_topic`, `save_flashcards` and the like) arrive with the
  features they write to.

## Evidence

`make eval-chat ARGS=--yes` asks 10 questions, spread across the 62-question
golden set, through the real assistant: "Where did my lecturer explain
...?".

- In 10 of 10 answers, a verified citation points at an expected page.
- 64% of all citations land on a listed page; the rest are related pages the
  golden set does not list.
- There were no failures, and the run cost £0.20 (about 2p per question).
- Two of the ten questions led Claude to search again with its own query.

## Consequences

- Changing the prompt means a new `chat.vN.md` file. Each interaction records
  the prompt version it used.
- Adding a tool means adding a Pydantic input model and a handler that goes
  through the scoped services. Destructive tools can only create pending
  actions.
