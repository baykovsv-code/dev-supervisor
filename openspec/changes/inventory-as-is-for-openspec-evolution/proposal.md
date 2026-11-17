# Proposal

## Why

Development Supervisor grew its own requirements, architecture, planning, ticket,
approval, and archival machinery before the project adopted OpenSpec. Before further
development, the project needs an evidence-based AS-IS inventory that separates this
duplicated workflow from the useful orchestration ideas worth retaining, and that
defines a less rigid, quota-efficient path suitable for startup-style iteration.
The completed inventory and subsequent Harness Engineering analysis now need to be
synthesized into an explicit target architecture before a migration roadmap can be
derived; migration task order must not silently decide the architecture.

## What Changes

- Produce a traceable AS-IS inventory of the current controller, state machine,
  policies, schemas, prompts, tests, operator workflows, and runtime boundaries.
- Compare each Supervisor capability with the installed OpenSpec workflow and classify
  it as retain, replace with OpenSpec, integrate, simplify, retire, or unresolved.
  Record evidence and avoid treating name similarity as behavioral equivalence.
- Identify which strict controls are durable safety or correctness invariants and
  which are accidental ceremony that can become risk-based defaults or optional
  profiles for early-stage product work.
- Preserve and refine the original product intent: decompose sufficiently formalized
  product requirements into specs, execute them through a state machine, observe and
  conserve model quota, request architecture decisions when needed, and escalate to a
  user only at meaningful decision points.
- Define candidate target boundaries in which OpenSpec owns specification/change
  artifacts and Development Supervisor becomes a thinner execution and governance
  layer instead of maintaining a parallel planning format.
- Preserve the Harness Engineering analysis in English and Russian, distinguishing
  useful mechanisms, author-reported claims, current implementation evidence, and
  recommendations requiring validation.
- Build a coherent target architecture in English and Russian from the AS-IS
  inventory, installed OpenSpec evidence, book analysis, current operator contracts
  and tests, and reconciled historical/2.1 intent. Compare improving the current
  controller, extracting a thin executor, and building a replacement core; select
  and justify one without assuming a rewrite or copying the book's pipeline.
- Define ownership, interfaces, lifecycle, durable state, task/context identity,
  task-wide budgets and stagnation detection, acceptance and deferred findings,
  selective independent review, enforceable role permissions, and preservation of
  quota/Git/checkpoint/recovery invariants. Specify evaluation evidence and resolve
  architecture-blocking choices before starting roadmap construction.
- Include a Detail + Pragmatic critic pair for both specification and code review:
  Detail identifies concrete defects, while Pragmatic assesses which findings justify
  another iteration or authorized deferral. Define their independent contexts,
  structured findings/dispositions, budget accounting and deterministic arbitration;
  neither critic may waive mandatory requirements, checks or authority boundaries.
- Deliver a staged migration roadmap with decision points, acceptance measures,
  compatibility concerns, and safe deletion criteria. The roadmap must favor
  incremental transition over a big-bang cutover and derive its slices from the
  completed target architecture, even if that architecture selects a new core.
- Treat `docs/dev-supervisor-discussion-2026-09-25.md` as historical reference rather
  than as current authority, and explicitly reconcile useful ideas from it with the
  current code and documentation.
- Make no runtime behavior, schema, or public CLI changes in this inventory change.

## Capabilities

### New Capabilities

None. This is a planning and documentation change; it does not introduce durable
system behavior and therefore declares `skip_specs: true`.

### Modified Capabilities

None.

## Impact

- Adds an AS-IS assessment, bilingual book analysis, bilingual target architecture,
  and only then an architecture-derived OpenSpec-alignment/migration plan to project
  documentation. Existing dated inventory reports remain historical assessment
  snapshots, not the authoritative final target design.
- Reads across `supervisor.py`, policy and state schemas, prompts, tests, operator and
  architecture documentation, OpenSpec configuration, and generated OpenSpec
  workflows; uses the user-supplied Harness Engineering PDF as attributed analysis
  input without copying the book into the repository.
- Does not modify controller code, persisted runtime state, managed projects, Git
  authority, quota authorization, or existing safety behavior.
- Establishes the review basis for later OpenSpec changes that may simplify or replace
  existing components; those changes require separate proposals and explicit approval.
