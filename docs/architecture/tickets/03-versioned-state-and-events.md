# T03: Versioned state, audit, and migration primitives

## Objective

Provide the durable primitives required for new lifecycles and safe conversion without
turning Supervisor into a distributed platform.

## Scope

- Define versioned schemas for runtime state, approval identity, plan epochs, engine
  identity/capabilities, and audit events.
- Implement pure dry-run migrations with explicit supported source/target versions.
- Add checksums and immutable predecessor linkage.
- Preserve snapshot-based operation unless a narrowly justified event journal is
  necessary; avoid speculative infrastructure.
- Add fault injection around durable writes and reconciliation.

- Files/modules: `supervisor.py`, `schemas/`, `tests/`.

## Acceptance criteria

- Malformed, ambiguous, newer, or unsupported state is never rewritten.
- Dry-run and apply use the same validated transformation and produce deterministic
  reports.
- Re-running an applied migration is idempotent.
- Existing valid state fixtures retain semantic identity.

## Non-goals

- multi-host locking;
- live migration during a model process.
