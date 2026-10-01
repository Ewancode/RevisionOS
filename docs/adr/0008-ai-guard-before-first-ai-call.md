# 8. Budget guard before the first AI call

Date: 2026-10-01 · Status: Accepted (changes the phase order in ARCHITECTURE.md section 15)

## Context

Phase 3 includes Claude vision transcription of pages whose maths text is
damaged, but the components that make Claude calls safe — the client
wrapper, usage recording and the BudgetGuard (section 8) — were scheduled
for Phase 5. Building Phase 3 as written would have meant real API spending
with no cap. The user chose to bring the guard forward.

## Decision

Phase 3 includes a minimal AI layer (`app/ai/`):

- `ClaudeClient` — the only code that calls Anthropic. It resolves a task to
  a model and effort from `config/ai.yaml` (ADR 6), checks the budget against
  the call's **worst-case** cost (estimated input plus the full output
  allowance) *before* sending, and records every call in `ai_interactions`
  and its tokens and estimated cost in `ai_usage` — including refused,
  truncated and failed calls.
- `BudgetGuard` — daily and monthly caps in the user's currency (GBP,
  converted from USD at a deliberately high rate) with day and month
  boundaries in Europe/London. At the cap, AI calls stop with
  `ai_budget_reached`; everything else keeps working.
- Server-side refusal fallback (`fallbacks: "default"`) is opted into per
  model (`server_fallback` in `ai.yaml`; on for Sonnet and Opus). Cost is
  computed from the model that actually answered; an unknown fallback model
  is priced as the most expensive configured model.
- No API key → the client reports `ai_not_configured` and documents still
  process, with damaged pages flagged for review.
- Prompts are versioned files (`app/ai/prompts/*.vN.md`); each interaction
  records the version.

Phase 5 extends this layer (usage dashboard, chat, tools, caching) rather than
replacing it.

## Consequences

Spending is capped from the first call. Phase 5 is smaller. Prompt caching is
not yet used; transcription sends one page per call, where caching the system
prompt would save little.
