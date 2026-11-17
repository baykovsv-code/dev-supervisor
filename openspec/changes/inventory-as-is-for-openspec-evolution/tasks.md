# Tasks

Initial delivery (2026-11-18): inventory/comparison and the candidate operating
model were completed in English and Russian, stopping before the roadmap. Reports:
`docs/architecture/as-is-openspec-inventory.md` and `.ru.md`; structural evidence:
`docs/architecture/as-is-openspec-evidence.json`. Their task references describe that
original delivery. Completed tasks 1–4.4 remain completed assessment work, not proof
that the target architecture below has been designed.

Scope update (2026-11-18): save the Harness Engineering analysis in EN/RU and synthesize
all source material into a coherent target architecture **before** roadmap authoring.
Group 5 is new architecture work; former roadmap group 5 is now group 6 and former
complete-assessment gate 6.1 is now 7.1. Groups 5–7 remain pending. This update does
not implement the architecture, run benchmarks, complete or archive the change.

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

- [x] 4.5 Save the complete Harness Engineering analysis in `docs/architecture/harness-engineering-analysis.md` and `.ru.md`, including PDF identity/page references, project evidence, useful mechanisms, limitations, rewrite alternatives and the proposed bounded evaluation; verify local links and EN/RU agreement, distinguish recommendations from selected architecture, and do not copy the PDF or private runtime data.

## 5. Synthesize and validate the target architecture before the roadmap

- [ ] 5.1 Create `docs/architecture/openspec-supervisor-target-architecture.md` and `.ru.md` with a source-to-decision matrix covering inventory C1–C12, installed OpenSpec evidence, the book analysis, current operator contracts/tests, and reconciled original/2.0/2.1 intent; verify each material idea/control has an adopt/adapt/defer/reject disposition, evidence, rationale, owner and invariant impact, and contradictions are explicitly reconciled.
- [ ] 5.2 Compare adapting the controller, extracting a thin executor and building a replacement core/full rewrite; select and justify an architecture using simplicity, operational/implementation cost, quota efficiency, testability and preservation of required guarantees; verify every alternative has concrete tradeoffs and the selected approach names evidence that would invalidate it, without using code size or book scores as sufficient justification.
- [ ] 5.3 Define the selected components, interfaces/data flow, single sources of truth, minimal lifecycle versus blocked reasons, durable state/receipt ownership and stable task identity under edits/reorder/archive; verify each C1–C12 responsibility is mapped to an owner/interface and retained/replaced controls have explicit evidence requirements, with no parallel editable plan or unexplained framework/service.
- [ ] 5.4 Specify task-wide durable budgets across all roles/restarts, resource accounting/enforcement limits, progress/stagnation and changed repair hypotheses, context manifests/versioned inputs/invalidation, mandatory acceptance versus authorized deferral/new work, and the user-selected Detail + Pragmatic pair for both spec and code review, with independent read-only contexts, explicit triggers/fast paths, evidence-bearing findings, per-finding dispositions, deterministic arbitration and accounting of both roles; verify representative success, unchanged-failure, exhausted-budget, stale-review, critic disagreement, unsupported findings, optional-polish and failed-mandatory-check trajectories have unambiguous outcomes without quota forecasting or score-only acceptance.
- [ ] 5.5 Specify enforceable role authority across tools/filesystem/shell/subprocesses, behavior when enforcement is unavailable, ordinary versus protected acceptance tests, and preservation of single writer, immutable engine identity where required, quota/checkpoint/Git/audit/recovery invariants; verify interruption and repeated-resume trajectories around consumption, invocation, report, verification, commit and push cannot silently gain authority, duplicate effects or accept file existence as completion.
- [ ] 5.6 Define a bounded end-to-end OpenSpec-task evaluation with normal completion, interruption, failed verification and repeated resume, mapping existing regression/fault tests and missing acceptance evidence to required invariants, and define spec/code Detail + Pragmatic review cases for blockers, optional polish, unsupported findings, disagreement, input changes and exhausted budget; verify fixtures, version/input identities, resource limits, baseline, outcome/call/time/intervention metrics and decision criteria are reproducible on paper, unknown economics stay explicit, and implementing/running the experiment is deferred to a separate scoped change.
- [ ] 5.7 Validate the complete target architecture for source coverage, ownership/interface consistency, simplicity, invariant/evaluation coverage, Detail + Pragmatic contracts for both spec and code, and EN/RU agreement; record the reviewed document revision/content identity and decision provenance, resolving all architecture-blocking choices through the existing autonomous/architecture/user decision model; verify no roadmap content is authored until this readiness record exists and no material user-owned decision is inferred from silence.

## 6. Produce an architecture-derived incremental evolution roadmap

Prerequisite: tasks 5.1–5.7 are complete, with a selected architecture and its readiness
record. Roadmap authoring must not make unresolved architectural decisions implicitly.

- [ ] 6.1 Derive small dependency-ordered future OpenSpec changes from the selected target architecture, linking each slice to its architectural contracts and including the bounded evaluation before retirement of parallel planning machinery; verify every slice has an observable outcome, prerequisites, preserved invariants, rollback point and non-goals, and even a replacement core uses an incremental transition rather than an assumed big-bang cutover.
- [ ] 6.2 Add architecture-backed deletion criteria for legacy states, commands, schemas, prompts, compatibility code and historical documentation; verify no removal is recommended without replacement coverage, retained recovery evidence where required, and a test or observation proving the old path is no longer authoritative.
- [ ] 6.3 Add a concise user-review checklist covering the selected architecture/ownership, startup assurance defaults, architecture autonomy, mandatory escalation and migration priorities; verify unresolved evidence items are distinct from decisions, block only affected future slices, and do not conceal an unfinished architectural choice.

## 7. Validate the complete assessment, architecture and roadmap

- [ ] 7.1 Cross-check the inventory, bilingual book analysis, bilingual target architecture and architecture-derived roadmap against the proposal/design and source-to-decision record; verify local links, EN/RU decision/limit agreement and readiness-before-roadmap evidence, run `python3 scripts/check_documentation.py`, `git diff --check` and `openspec validate inventory-as-is-for-openspec-evolution --strict --no-interactive`, and verify all checks pass or every pre-existing/unrelated failure is recorded with evidence.

## Workflow follow-up

- Review the selected architecture and roadmap before opening implementation changes; user-owned decisions require explicit authority, not approval inferred from artifact readiness.
- Create separate OpenSpec changes for accepted implementation/evaluation slices; do not implement or benchmark the target architecture from this documentation change.
- Archive this change only after the assessment/architecture/roadmap are accepted and follow-up changes are traceable.
