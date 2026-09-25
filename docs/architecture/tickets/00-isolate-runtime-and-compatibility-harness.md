# T00: Isolate the live runtime and establish rolling compatibility

## Objective

Make it impossible for ordinary development commits in this repository to hot-change
the Supervisor engine used by the live legacy reference project, and make compatibility with
its T30 checkpoint a deterministic completion gate for every later ticket.

## Operational precondition

Before the model run, an operator creates a detached engine checkout at extraction
commit `41f6757`, binds the live legacy reference project to it, and proves that `./dev status`
returns the unchanged T30 `HUMAN_GATE`. The development model must not edit either the
live project or that checkout.

## Scope

- Add a redacted, checksummed fixture preserving the structural semantics of the live
  T30 policy, path-only binding, state, quota/gate identity, plan frontier, and dirty
  product snapshot without credentials or personal content.
- Add a deterministic harness that runs a candidate engine against an isolated
  repository/runtime copy.
- Prove legacy launcher invocation, policy/state load, `status`, and no-model
  `HUMAN_GATE` resume/reconciliation.
- Assert byte-identical state, unchanged product HEAD/fingerprint and working tree,
  unchanged gate/quota/run evidence, and no model or network process.
- Make the compatibility test part of the normal discovered test suite so every later
  ticket verification executes it automatically.
- Document fixture refresh rules: only reviewed redacted snapshots with provenance and
  checksums may replace it.

- Files/modules: `tests/`, `docs/`.

## Acceptance criteria

- The live binding and detached engine revision are recorded as operator evidence but
  are not modified by the ticket model.
- The new harness fails if a candidate mutates state during status/no-model resume,
  rejects the supported legacy policy/state, starts a model/network process, or changes
  the product snapshot.
- The full AS-IS suite plus the new compatibility test passes.
- Later tickets require no live legacy-reference access to run the harness.

## Non-goals

- converting live state;
- releasing the T30 evidence gate;
- activating a 2.0 candidate on the live project.
