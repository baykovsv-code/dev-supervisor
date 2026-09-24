# T11: Qualified 1.x to 2.0 cutover

## Objective

Implement R15 using the state/schema and engine-update foundations.

## Scope

- Define supported 1.x quiescent source states and explicit rejection reasons.
- Archive exact engine revision, policy, state, quota ledger, artifacts, Git identity,
  lock ownership, and checksums.
- Dry-run and apply deterministic conversion with predecessor lineage.
- Atomically switch binding, reconcile read-only, require human go/no-go, and support
  rehearsed rollback.
- Ensure consumed quota authorization is never reused.

- Files/modules: `supervisor.py`, `schemas/`, `tests/`.

## Acceptance criteria

- Conversion changes neither product HEAD nor working tree.
- Ambiguous, active, dirty-unsupported, or unknown source states are rejected without
  writes.
- Exactly one controller and lock authority exists before and after switch/rollback.
- Golden real-state fixtures pass dry-run and invariant checks.

## Non-goals

- migrating an active model/check/commit;
- deleting the predecessor archive.
