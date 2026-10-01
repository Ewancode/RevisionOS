# 6. Per-task effort levels in AI routing

Date: 2026-10-01 · Status: Accepted (amends ARCHITECTURE.md section 8, "Model routing defaults")

## Context

Section 8 routes each task type to a model and escalates to a stronger model
when quality demands it. On current Claude models the **effort** setting
(`low`, `medium`, `high`, `xhigh`, `max`) controls thinking depth and token
spend within one model, and is the main cost/quality lever:

- Defaults differ by model (Opus 5.5 defaults to `medium`, Sonnet 5.5 to
  `high`), so leaving effort unset lets an API default decide our cost.
- Thinking cannot be switched off on Opus 5.5 (and only via a special mode on
  Sonnet 5.5); lowering effort is the supported way to make routine calls cheap.
- Haiku 4.5 does not accept the effort parameter at all.
- Prompt caches are per model, so escalating to a different model forfeits
  the cache; raising effort on the same model keeps it.

## Decision

- Each route in `backend/config/ai.yaml` is a **step** (model + effort), with
  an optional `escalate_to` step that may change the model, the effort, or both.
- Each model declares the `effort_levels` it accepts. Validation at startup
  requires an explicit effort for models that support it, rejects one for
  models that don't, and rejects an escalation identical to the first step.
- Starting values: Haiku for high-volume short tasks (no effort); Sonnet at
  `medium` for tutoring, explanations, guides and document analysis; Sonnet at
  `high` for maths transcription, proof marking and exam-level questions,
  escalating to Opus at `high` as section 8 specifies.
- When tuning (Phase 5 onwards, against the evaluation sets), try a different
  effort on the same model before adding a model escalation.

## Consequences

Cost per task is explicit and reviewable in one file. The orchestration layer
(Phase 5) passes `output_config.effort` from the route and omits it for models
without effort levels.
