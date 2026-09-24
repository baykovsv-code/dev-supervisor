# T10: Immutable engine identity and multi-host update

## Objective

Make engine receipt and activation safe when repositories are synchronized across
computers.

## Scope

- Replace path-only binding with immutable revision/build identity and compatibility
  ranges.
- Stage updates outside the active controller and verify provenance, integrity,
  schemas, protocols, tests, and state migration dry-run.
- Add quiescent switch, read-only reconciliation, go/no-go, archive, and rollback.
- Make stale hosts fail closed before writing newer state.
- Define one-writer host ownership/lease appropriate to the local deployment model.

- Files/modules: `supervisor.py`, `schemas/`, `tests/`.

## Acceptance criteria

- An active process never observes a partially updated engine tree.
- Old/incompatible hosts cannot modify new state.
- Update and rollback preserve product HEAD/fingerprint and never create dual control.
- Git synchronization alone cannot satisfy writer ownership.
- Fault tests cover every binding and archive boundary.

## Non-goals

- a general cluster coordinator;
- hot code reload.
