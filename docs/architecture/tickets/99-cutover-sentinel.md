# T99: Cutover sentinel — not executable under Supervisor 1.x

## Purpose

This ticket exists only because Supervisor 1.x cannot finish the final plan ticket
cleanly. The configured milestone after T12 must stop at a human gate before T99.

- Files/modules: `docs/architecture/`.

## Mandatory behavior

- Do not release the post-T12 gate under Supervisor 1.x.
- Do not invoke an implementation or architecture model for T99.
- Human reviewers inspect qualification evidence and decide whether to activate the
  immutable 2.0 generation using the approved runbook.
- Human reviewers confirm the final pre-cutover documentation review from T12,
  including manifest, pair/link/staleness results, current operator workflows, and
  retained migration/rollback/compatibility/cutover evidence.
- If approval is withheld, remain quiescent; do not infer another ticket.

## Documentation impact

`None — human evidence gate only.` T99 changes no documentation; it verifies the
documentation evidence produced by T12 and remains non-executable.

T99 has no implementation acceptance criteria and must never produce a commit.
