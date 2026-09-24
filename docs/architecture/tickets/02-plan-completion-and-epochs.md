# T02: Plan completion and versioned epochs

## Objective

Replace the 1.x final-ticket failure with an explicit, crash-safe plan lifecycle.

## Scope

- Add stable plan-epoch identity and immutable linkage to prior epochs.
- Reconcile the last ticket's verified commit into `PLAN_COMPLETED` atomically and
  idempotently.
- Ensure completed plans never start a model or infer a new ticket.
- Represent current frontier, final result, evidence, and completion reason in status.
- Add state/schema migration and recovery tests at every final-commit boundary.

- Files/modules: `supervisor.py`, `schemas/`, `tests/`.

## Acceptance criteria

- Normal and interrupted final-ticket paths produce one commit and one completed
  epoch.
- Resume from `PLAN_COMPLETED` is read-only until a separately approved epoch exists.
- Previous plan identity, ticket frontier, and audit evidence remain accessible.
- Unsupported legacy end states fail closed with a migration report.

## Non-goals

- selecting backlog work;
- changing Git push semantics.
