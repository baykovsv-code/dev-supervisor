# Supervisor 2.0 dependency-ordered implementation plan

Status: **PROPOSED — not executable before human approval of the architecture
baseline**.

This is the canonical Supervisor-compatible plan/index. Each ticket is bounded and
must preserve the AS-IS suite unless its approved acceptance criteria intentionally
replace behavior. Architecture documents are protected; implementation may not amend
them silently.

| Milestone | Tickets | Gate |
|---|---|---|
| 0 compatibility isolation | 00 | Live PA pinned to AS-IS; redacted T30 compatibility harness passes |
| 1 safety foundation | 01 → 02 → 03 | Config/capability, lifecycle, and rolling PA compatibility invariants pass |
| 2 project admission and renewal | 04 → 05 → 06 | Scenario A/B/C fixtures pass; no implementation before approval |
| 3 controlled operations | 07 → 08 → 09 | Quota, mutation, and push denial/recovery tests pass |
| 4 upgrades and migration | 10 → 11 | Multi-host update and 1.x conversion/rollback rehearsals pass |
| 5 qualification | 12 | Isolated personal-assistant rehearsal and operator review |
| 6 cutover boundary | 99 | HUMAN_GATE; never execute T99 under Supervisor 1.x |

The exact order is **T00 → T01 → T02 → T03 → T04 → T05 → T06 → T07 → T08 → T09 → T10 → T11 → T12 → T99**.

T99 is a deliberate sentinel for the known 1.x missing-final-ticket transition. The
old controller must enter the configured milestone gate after T12 and must not release
that gate. Cutover and post-cutover self-development belong to the approved 2.0
controller generation.

## Global delivery rules

- No ticket may enable self-modification, out-of-plan modification, or push by default.
- Repository content cannot elevate host capabilities.
- No ticket may implement quota prediction or restore
  `forecast.fallback_ticket_hours`.
- Every persisted state/schema change includes compatibility, crash, and rejection
  tests.
- T00 establishes a redacted real-state compatibility harness. Every T00–T11 ticket
  must pass it before commit; a schema-changing ticket owns its legacy reader,
  migration dry-run, rejection path, and rollback rather than deferring them.
- The live `personal-assistant` remains bound to detached AS-IS commit `41f6757`.
  Intermediate development revisions are never activated on it.
- No live `personal-assistant` write is permitted before T12 qualification and the
  final human gate.
