# T04: Cold start requirements and architecture review

## Objective

Implement R01/R02 for a new project that begins with a user specification.

## Scope

- Preserve the source specification and lineage every proposed revision.
- Add explicit requirements and architecture review states with version-bound approval.
- Produce goals, constraints, unknowns, conflicts, non-goals, alternatives, complexity
  rationale, system boundaries, data/integrations, and risks.
- Support zero or more user correction iterations and safe resume.
- Create a plan only after explicit approval of exact requirements and architecture
  versions.

- Files/modules: `supervisor.py`, `prompts/`, `schemas/`, `tests/`.

## Acceptance criteria

- No plan, tickets, or product delta exists before approval.
- Silence, partial agreement, stale approval, or later edits do not authorize planning.
- One and multiple correction rounds resume without losing lineage.
- Status identifies exact versions and the required human action.
- The T00 legacy-reference compatibility harness passes unchanged; the new cold-start
  states do not reinterpret an existing T30 execution state.

## Non-goals

- admitting a repository with pre-existing code;
- autonomous product-owner decisions.
