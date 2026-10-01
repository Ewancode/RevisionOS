# 4. Secrets in the environment; tunables in validated YAML

Date: 2026-10-01 · Status: Accepted (ARCHITECTURE.md section 4)

## Context

The spec forbids hard-coded secrets and magic numbers. The learning engine
and AI layer depend on many numbers that will be tuned over time.

## Decision

- **Secrets and wiring** (database URL, Redis URL, Anthropic key) come from
  environment variables via pydantic-settings (`app/core/settings.py`), held
  as `SecretStr` so they never appear in reprs or logs. `.env` is git-ignored;
  `.env.example` documents every variable.
- **Tunables** live in `backend/config/learning.yaml` and `ai.yaml`, validated
  at startup by typed Pydantic models (`app/core/config.py`) with ranges and
  cross-field rules (e.g. every route names a known model; daily cap ≤
  monthly cap). Unknown keys are rejected, so a typo fails loudly.
- Claude model IDs appear only in `ai.yaml`; a test enforces this.
- Config sections are added in the phase that first uses them, with values
  taken from ARCHITECTURE.md. Numbers the design leaves open (e.g. Elo K,
  priority weights) are chosen and documented in that phase.

## Consequences

Changing a weight is a reviewed one-line diff, and an invalid edit cannot
reach a running system.
