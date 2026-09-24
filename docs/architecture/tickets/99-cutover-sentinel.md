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
- If approval is withheld, remain quiescent; do not infer another ticket.

T99 has no implementation acceptance criteria and must never produce a commit.
