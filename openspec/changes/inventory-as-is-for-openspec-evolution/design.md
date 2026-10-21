# Design

## Context

See `proposal.md` for motivation. The current implementation is a roughly 10,000-line
single-file Python controller with a large command surface, versioned policy/state
schemas, prompt contracts, and more than 5,000 lines in its main test module. It owns
both planning lifecycle concerns and runtime execution safeguards. OpenSpec 1.14.3 is
now initialized, but there are no main specs or prior OpenSpec changes to treat as a
behavioral baseline.

The inventory must distinguish documented intent from behavior supported by code and
tests. It must also distinguish OpenSpec's artifact/change lifecycle from Supervisor's
host-local responsibilities such as quota authorization, process control, Git
checkpointing, idempotent recovery, and human authority. The added discussion document
is useful historical input, but current code, tests, schemas, configuration, and
operator documentation take precedence when they disagree.

## Goals / Non-Goals

**Goals:**

- Create a reproducible inventory whose claims link to concrete files, commands,
  states, schemas, or tests and identify the inspected Git and OpenSpec versions.
- Expose both functional overlap with OpenSpec and complexity that exists independently
  of that overlap.
- Define a candidate ownership boundary between OpenSpec planning artifacts and a thin
  Supervisor runtime orchestrator.
- Define a decision/escalation model that permits bounded autonomous architecture
  choices while reserving material product, risk, and irreversible choices for the
  user.
- Define measurable principles for a lower-ceremony startup workflow without silently
  weakening essential safety, quota, or recovery invariants.
- Turn findings into small, dependency-ordered follow-up OpenSpec changes with explicit
  validation and rollback boundaries.

**Non-Goals:**

- Changing runtime behavior, state schemas, policies, prompts, or CLI commands.
- Migrating the ignored `.dev-supervisor/` runtime or reconnecting any previously
  managed project.
- Claiming that OpenSpec replaces process supervision, quota authorization, Git
  transactionality, or operator authority without evidence.
- Preserving every 1.x/2.0 compatibility path indefinitely merely because it exists.
- Designing a generic ALM platform, distributed scheduler, or multi-host coordinator.

## Decisions

### 1. Produce one reviewable assessment with fact and recommendation layers

The apply phase will create `docs/architecture/as-is-openspec-inventory.md`. Each
section will separate observed AS-IS evidence, interpretation, and recommendation so a
future contributor can challenge a conclusion without rediscovering its source.

The document will include:

- baseline identity and inventory method;
- component and responsibility map;
- lifecycle/state and model-invocation map;
- human-decision and architecture-decision map;
- quota, verification, Git, recovery, and authority controls;
- an OpenSpec overlap/ownership matrix;
- rigidity and quota-cost analysis;
- candidate target boundary and startup-oriented operating modes;
- incremental migration roadmap, acceptance measures, and deletion criteria;
- unresolved evidence gaps and decisions requiring user review.

Alternative: split facts, target architecture, and roadmap into several documents.
That would make the first review harder to keep internally consistent. Splitting can
happen in later approved changes once the boundary is accepted.

### 2. Use a fixed classification matrix instead of prose-only comparison

Every material Supervisor responsibility will receive one classification:

- **retain** — differentiated runtime or safety value not supplied by OpenSpec;
- **delegate to OpenSpec** — OpenSpec should be the source of truth;
- **integrate** — both systems have a role with an explicit interface;
- **simplify** — preserve the outcome with less state, ceremony, or repetition;
- **retire** — historical, redundant, or no longer justified behavior;
- **unresolved** — evidence or a bounded experiment is required.

Each row will name evidence, current owner, proposed owner, safety consequence,
migration dependency, and confidence. OpenSpec behavior will be derived from the
installed CLI/workflows and versioned official documentation, not from labels alone.

Alternative: begin from the desired target and document only components that survive.
That would bias the inventory toward a rewrite and make deletion criteria unauditable.

### 3. Treat a thin orchestrator over OpenSpec as the target hypothesis

The assessment will evaluate a boundary where OpenSpec owns proposals, requirements,
specs, design, tasks, artifact dependencies, validation, synchronization, and archival.
Supervisor should own only concerns that require runtime coordination or stronger
local authority: bounded scheduling, observed quota authorization, model-process
control, deterministic checks, checkpoint identity, Git transaction boundaries,
idempotent recovery, audit, and escalation.

Supervisor state should eventually reference stable OpenSpec change/task identities
and content digests instead of copying a second plan/ticket hierarchy. This is a target
hypothesis, not authorization to implement the adapter in this change.

Alternatives considered:

- Keep the existing planning machine and merely store OpenSpec files beside it. This
  preserves duplicate sources of truth and most current ceremony.
- Replace Supervisor entirely with OpenSpec. This discards quota-aware execution,
  runtime checkpointing, and recovery behavior that OpenSpec does not claim to own.
- Rewrite Supervisor from scratch immediately. This loses tested invariants before the
  replacement boundary is understood.

### 4. Evaluate controls by risk and cost, not by whether they are strict

For every gate or state family, the inventory will record the protected failure mode,
when the control runs, deterministic work versus model work, user interaction, expected
quota cost, and evidence that the control has caught a real or tested fault. The target
recommendation will separate:

- always-on invariants for authority, duplicate side effects, checkpoint identity,
  secrets, quota consumption, and irreversible Git operations;
- risk-triggered architecture and human gates;
- configurable assurance appropriate to exploration, ordinary startup delivery, and
  protected/release work;
- historical compatibility and migration controls that can be retired after explicit
  evidence and retention criteria are satisfied.

The inventory will not recommend a bypass flag or a generic force-state mechanism.
Lower ceremony must come from fewer duplicated artifacts, deterministic fast paths,
bounded defaults, and evidence-based escalation.

Alternative: define one universally relaxed mode. That would conflate speed with
unbounded authority and make failures harder to diagnose.

### 5. Make architecture escalation explicit and economical

The target decision matrix will distinguish:

- decisions an implementation agent may make autonomously because they are local,
  reversible, within an approved spec, and within declared complexity limits;
- decisions that require an architecture pass because they affect component
  boundaries, persistent data, public contracts, trust boundaries, dependencies, or
  operational cost;
- decisions that require the user because they change product intent, risk tolerance,
  external commitments, irreversible data/history, credentials/authority, or choose
  among materially different trade-offs.

Deterministic preflight and existing OpenSpec artifacts should be reused before any
model call. Repeated discovery, unchanged retries, duplicate reviews, and model calls
for mechanically decidable transitions are explicit optimization targets. The
inventory will propose budgets and measurements, but it will not introduce quota
forecasting.

Alternative: require user approval for every architecture result. This is safe but
defeats autonomous progression and spends quota re-establishing context. Fully
autonomous architecture approval is also rejected because product and authority
decisions remain the user's responsibility.

### 6. Require incremental migration slices with an operable rollback point

The roadmap will order future changes so that each removes or redirects one coherent
source of truth, retains a working entry path, and has observable acceptance criteria.
Likely slices are: freeze the ownership contract; introduce read-only OpenSpec
discovery; execute one bounded OpenSpec task through existing runtime controls; replace
parallel plan/ticket materialization; simplify decision gates and profiles; then retire
obsolete schemas, commands, and migration-only code.

The exact slices remain findings of the inventory. No deletion may be proposed without
naming replacement coverage, retained historical evidence, and a rollback or recovery
story.

Alternative: preserve compatibility across every old and new path throughout the
whole migration. That minimizes short-term deletion risk but compounds the state space
and directly conflicts with the simplification goal.

## Risks / Trade-offs

- **Confirmation bias toward OpenSpec** → Require per-row behavioral evidence and allow
  `retain` or `unresolved` when OpenSpec has no equivalent.
- **Inventory becomes another permanent planning system** → Keep it time-stamped,
  versioned, and explicitly feed accepted findings into small follow-up OpenSpec
  changes rather than adding executable state to it.
- **Relaxation removes a valuable invariant** → Tie every simplification to a protected
  failure mode, tests/evidence, and a replacement control before proposing deletion.
- **OpenSpec evolves after the comparison** → Record CLI/workflow versions and make
  capability verification repeatable.
- **Scope expands into a rewrite** → Restrict this change to documentation and require
  separate approval for every implementation slice.
- **Quota-cost claims are speculative** → Distinguish measured call sites and repeated
  transitions from estimates; mark unavailable runtime evidence explicitly.
- **Historical runtime data contains private context** → Use tracked sources and
  redacted aggregate evidence by default; do not copy ignored run logs or managed
  project data into the assessment.

## Migration Plan

This change has no runtime deployment. Apply it by producing the assessment, running
documentation and OpenSpec validation, and obtaining a user review of the ownership
boundary and roadmap. If rejected, remove or revise the new assessment; no controller
or runtime rollback is required. Accepted roadmap slices become separate OpenSpec
changes and must carry their own compatibility and rollback plans.

## Open Questions

- Which existing runtime histories are safe and useful enough to measure actual model
  calls and stop reasons, rather than relying only on static call-site analysis?
- After the inventory identifies migration-only paths, how long should their local
  recovery evidence be retained before code removal?
- Should the eventual OpenSpec integration consume the CLI as a subprocess or a more
  stable machine-readable interface if one is available at implementation time?
