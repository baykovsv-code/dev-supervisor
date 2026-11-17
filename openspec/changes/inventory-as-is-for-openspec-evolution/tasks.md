# Tasks

Delivery scope (2026-11-18): the user requested inventory/comparison through the
candidate operating model, in English and Russian, stopping before the incremental
migration roadmap. Reports: `docs/architecture/as-is-openspec-inventory.md` and
`docs/architecture/as-is-openspec-inventory.ru.md`; structural evidence:
`docs/architecture/as-is-openspec-evidence.json`. Groups 5 and the complete-assessment
gate 6.1 remain pending; this delivery does not complete or archive the change.

## 1. Establish the evidence baseline

- [x] 1.1 Create `docs/architecture/as-is-openspec-inventory.md` with the inspected Git commit, OpenSpec CLI/workflow versions, inventory date, authoritative tracked sources, and evidence rules; verify every source path resolves and no ignored runtime or managed-project content is copied into the document.
- [x] 1.2 Inventory the tracked components in `supervisor.py`, `schemas/`, `prompts/`, `tests/`, policy/configuration, and operator/architecture documentation; verify every component has a stated responsibility and at least one code, schema, test, command, or document reference.
- [x] 1.3 Reconcile `docs/dev-supervisor-discussion-2026-09-25.md` and the current 2.1 backlog against the implemented baseline, marking each material idea as implemented, still relevant, superseded, historical, or unsupported; verify no historical statement is presented as current behavior without corroborating evidence.

## 2. Model the AS-IS behavior and cost

- [x] 2.1 Document the current lifecycle, state families, CLI workflows, model-invocation points, deterministic transitions, architecture decisions, and human gates; verify all top-level CLI command families and persisted state families are represented or explicitly excluded with a reason.
- [x] 2.2 Build a control/invariant matrix for quota authorization, process bounds, checkpoint identity, verification, scope, Git mutation/push, capabilities, audit, recovery, migration, and engine handoff; verify each claimed guarantee is linked to executable code or tests and documentation-only intentions are labeled separately.
- [x] 2.3 Measure structural and quota-relevant complexity, including state/command/schema surface, repeated reviews, potential unchanged retries, and model versus deterministic steps; verify the document separates directly measured facts, static estimates, and unavailable runtime evidence.

## 3. Compare Supervisor with OpenSpec

- [x] 3.1 Record the capabilities of the installed OpenSpec version using its CLI, generated workflows, and version-matched official documentation, covering proposal/spec/design/task dependencies, validation, apply, sync, archive, and stores where relevant; verify every asserted OpenSpec capability cites a reproducible command or source.
- [x] 3.2 Create a complete overlap/ownership matrix that classifies each material Supervisor responsibility as retain, delegate to OpenSpec, integrate, simplify, retire, or unresolved and records current owner, proposed owner, evidence, safety consequence, migration dependency, and confidence; verify every component from task 1.2 is represented in the matrix.
- [x] 3.3 Identify duplicate sources of truth and handoff risks between OpenSpec artifacts and Supervisor plans, tickets, revisions, approvals, archives, and runtime state; verify each proposed OpenSpec delegation names what stops being authoritative and how split-brain state would be detected during migration.

## 4. Define the target operating model

- [x] 4.1 Document the candidate boundary in which OpenSpec owns specification/change artifacts and a thinner Supervisor owns bounded execution, quota, checkpoints, deterministic verification, Git transactionality, recovery, audit, and escalation; verify every responsibility has exactly one source of truth and an explicit interface where ownership crosses.
- [x] 4.2 Define evidence-based assurance modes for exploration, ordinary startup delivery, and protected/release work, separating always-on invariants from risk-triggered controls and historical compatibility paths; verify no mode permits generic force-state, duplicate side effects, implicit authority, unrecorded quota consumption, or irreversible Git mutation without the required authorization.
- [x] 4.3 Define the architecture and user-escalation decision matrix using reversibility, blast radius, public/data/trust-boundary impact, operational cost, requirement ambiguity, and trade-off materiality; verify representative decisions have an unambiguous autonomous, architecture-review, or user-decision route.
- [x] 4.4 Define quota-economy principles and measurements based on deterministic preflight, OpenSpec context reuse, bounded calls, no unchanged retries, and risk-triggered reviews; verify proposed metrics can be collected without quota prediction, secret exposure, or model calls solely for bookkeeping.

## 5. Produce an incremental evolution roadmap

- [ ] 5.1 Break the target into small dependency-ordered future OpenSpec changes, beginning with read-only integration and one bounded end-to-end task before removing parallel planning machinery; verify every slice has an observable outcome, prerequisites, preserved invariants, rollback point, and explicit non-goals.
- [ ] 5.2 Add deletion criteria for legacy states, commands, schemas, prompts, compatibility code, and historical documentation; verify no removal is recommended without replacement coverage, retained recovery evidence where still required, and a test or observation proving the old path is no longer authoritative.
- [ ] 5.3 Add a concise user-review checklist covering the proposed ownership boundary, acceptable startup assurance defaults, architecture autonomy, mandatory escalation points, and migration priorities; verify unresolved items are clearly separated from recommendations and block only the future slice they affect.

## 6. Validate the complete assessment

- [ ] 6.1 Cross-check the assessment against the proposal and design, run `python3 scripts/check_documentation.py`, `git diff --check`, and `openspec validate inventory-as-is-for-openspec-evolution --strict --no-interactive`, and verify all checks pass or every pre-existing/unrelated failure is recorded with evidence.

## Workflow follow-up

- Review and explicitly accept or amend the inventory's ownership boundary and roadmap before opening an implementation change.
- Create separate OpenSpec changes for accepted migration slices; do not implement the roadmap from this inventory change.
- Archive this change only after the assessment is accepted and its follow-up changes are traceable.
