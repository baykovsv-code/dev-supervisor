# Proposal

## Why

Development Supervisor grew its own requirements, architecture, planning, ticket,
approval, and archival machinery before the project adopted OpenSpec. Before further
development, the project needs an evidence-based AS-IS inventory that separates this
duplicated workflow from the useful orchestration ideas worth retaining, and that
defines a less rigid, quota-efficient path suitable for startup-style iteration.

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
- Deliver a staged migration roadmap with decision points, acceptance measures,
  compatibility concerns, and safe deletion criteria. The roadmap must favor
  incremental replacement over a big-bang rewrite.
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

- Adds an AS-IS assessment and an OpenSpec-alignment/migration plan to project
  documentation.
- Reads across `supervisor.py`, policy and state schemas, prompts, tests, operator and
  architecture documentation, OpenSpec configuration, and generated OpenSpec
  workflows.
- Does not modify controller code, persisted runtime state, managed projects, Git
  authority, quota authorization, or existing safety behavior.
- Establishes the review basis for later OpenSpec changes that may simplify or replace
  existing components; those changes require separate proposals and explicit approval.
