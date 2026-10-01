# Revision OS
Spec: docs/SPEC.md. Approved design: docs/ARCHITECTURE.md — follow it; if you
find a real problem with it, stop and tell me before changing course.

- Work one phase at a time (ARCHITECTURE.md section 15). Stop for my review after each.
- Every phase includes its tests. Run the full test suite before saying a phase is done.
- Never hard-code secrets. Never print or commit .env.
- Tunable numbers go in config/*.yaml, not code.
- Record any architectural change as an ADR in docs/adr/.