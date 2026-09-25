# T06: Backlog intake and new development cycles

## Objective

Implement scenario C from `PLAN_COMPLETED` to a new approved plan epoch.

## Scope

- Select an explicitly bounded set of backlog items without making raw items
  executable.
- Analyze requirements, dependencies, duplicates, readiness, and architecture impact.
- Support iterative architecture-delta correction and version-bound approval.
- Create the next plan/index, tickets, and frontier with lineage to source backlog
  items and the prior epoch.
- Record rejection, deferral, duplication, and missing-information reasons.

- Files/modules: `supervisor.py`, `prompts/`, `schemas/`, `tests/`.

## Acceptance criteria

- No backlog item reaches implementation without approved architecture and planning.
- Scope expansion invalidates affected approval.
- Prior epochs remain immutable.
- Status distinguishes completed plan, backlog review, approval wait, and ready epoch.
- The T00 legacy-reference compatibility harness passes unchanged, and its active T30
  epoch/frontier is neither completed nor rolled forward implicitly.

## Non-goals

- prioritizing work without user/product authority;
- silently editing a completed plan.
