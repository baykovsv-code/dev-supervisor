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
| 3 controlled operations | 07 → 08 → F09 → 09 | Quota, mutation, deterministic-verification recovery, and push denial/recovery tests pass |
| 4 upgrades and migration | 10 → F10 → F11 → 11 | Documentation baseline/current operator set and protected-snapshot recovery pass before 1.x conversion/rollback rehearsals |
| 5 qualification | F12 → 12 | macOS platform qualification, then isolated personal-assistant rehearsal and operator review |
| 6 cutover boundary | 99 | HUMAN_GATE; final documentation gate passes; never execute T99 under Supervisor 1.x |

The exact order is **T00 → T01 → T02 → T03 → T04 → T05 → T06 → T07 → T08 → F09 → T09 → T10 → F10 → F11 → T11 → F12 → T12 → T99**.

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
- Every pending and future ticket has an explicit `Documentation impact`
  classification. Behavior-changing tickets update affected normative English
  operator documentation and the affected maintained Russian operator subset in the
  same ticket.
- T00 establishes a redacted real-state compatibility harness. Every implementation
  ticket through F12 in authoritative plan order, including F09-F12, must
  pass it before commit; a schema-changing ticket owns its legacy reader,
  migration dry-run, rejection path, and rollback rather than deferring them.
- The live `personal-assistant` remains bound to detached AS-IS commit `41f6757`.
  Intermediate development revisions are never activated on it.
- No live `personal-assistant` write is permitted before T12 qualification and the
  final human gate.
- F12 must record qualification on an actual contemporary Apple Silicon macOS host;
  Linux-only tests, mocks, or the presence of POSIX APIs cannot satisfy that gate.
- The post-T12 cutover gate validates the translation manifest, deterministic
  pair/link/staleness checks, current English and maintained Russian operator
  workflows, and retention of migration/rollback/compatibility/cutover evidence.
