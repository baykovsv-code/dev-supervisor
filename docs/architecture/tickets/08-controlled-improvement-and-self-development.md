# T08: Controlled improvement and self-development

## Objective

Implement R11/R12 behind the default-off mutation capabilities.

## Scope

- Require an explicit user trigger for out-of-plan improvement.
- Add architecture impact, correction, approval, bounded plan/ticket, checks, and scope
  gates.
- Escalate changes exceeding bounded policy into a normal development cycle.
- Keep defect repair, ordinary bug fix, user improvement, and self-development distinct
  in state and audit.
- Build a successor Supervisor generation in isolation and activate it only through a
  later quiescent handoff.

- Files/modules: `supervisor.py`, `prompts/`, `schemas/`, `tests/`.

## Acceptance criteria

- Disabled capabilities permit analysis/status but no mutation.
- No autonomous feature request or silent bug-to-feature expansion occurs.
- Self-development cannot edit or activate the executing controller generation.
- Iterative architecture correction and interruption preserve lineage.

## Non-goals

- performing the activation protocol owned by T10/T11;
- automatic scope splitting to evade limits.
