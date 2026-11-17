# Design

## Context

See `proposal.md` for motivation. The completed inventory describes a roughly
10,000-line controller combining planning lifecycle and host-local execution safety.
The repository uses OpenSpec 1.14.3 with no main behavioral specs; this documentation
change declares `skip_specs: true`.

The initial delivery completed tasks 1–4 and deliberately stopped before a roadmap.
A subsequent review of the user-supplied Harness Engineering book produced additional
recommendations. On 2026-11-18 the user requested saving that analysis and requiring
architecture synthesis before roadmap construction. This refines the existing
assessment/evolution scope; it does not authorize runtime implementation.

Existing evidence:

- [AS-IS inventory, EN](../../../docs/architecture/as-is-openspec-inventory.md)
  and [RU](../../../docs/architecture/as-is-openspec-inventory.ru.md), with the
  [structural evidence manifest](../../../docs/architecture/as-is-openspec-evidence.json);
- [Harness Engineering analysis, EN](../../../docs/architecture/harness-engineering-analysis.md)
  and [RU](../../../docs/architecture/harness-engineering-analysis.ru.md), including
  PDF identity, chapter/page references, caveats and project mappings;
- current code, tests, schemas, operator contracts and installed OpenSpec workflows;
- the September discussion, completed 2.0 material and 2.1 backlog as reconciled intent.

The current code/tests establish implemented behavior; current English operator
material establishes the operating contract. Historical intent, book examples and
analysis recommendations do not independently authorize behavior. Book model/pricing/
performance claims are not validated merely by inclusion in this source set.

## Goals / Non-Goals

**Goals:**

- Preserve reproducible AS-IS evidence and the full bilingual book analysis.
- Produce an explicit, internally coherent target architecture before deriving a
  dependency-ordered migration roadmap.
- Make evidence-based adopt/adapt/defer/reject decisions across all source material,
  preserving strong existing safeguards and avoiding duplicated planning authority.
- Compare viable architecture alternatives and select one with an invariant/evidence
  argument, a simplicity rationale and conditions that would invalidate the choice.
- Define execution/context/budget/acceptance/permission/recovery contracts and an
  evaluation design sufficient to assess a later bounded implementation experiment.
- Keep meaningful autonomy and economical escalation: local reversible architecture
  decisions remain autonomous; material product/authority/tradeoff choices use the
  existing user-decision route.

**Non-Goals:**

- Changing runtime code, state schemas, policies, prompts, CLI or managed-project state.
- Implementing the target design, launching model benchmarks or qualifying a release.
- Treating the book's stage count, numerical scores, model routing or tools as defaults.
- Designing a generic ALM platform, plugin framework, distributed scheduler, memory
  service or multi-host coordinator without demonstrated need.
- Preserving every historical compatibility route indefinitely or deleting it without
  replacement and retention evidence.

## Decisions

### 1. Separate dated evidence from the future architectural decision

Keep the completed `docs/architecture/as-is-openspec-inventory.md` and `.ru.md` as
assessment snapshots. Save the book review in
`docs/architecture/harness-engineering-analysis.md` and `.ru.md`. These analyses
contain facts, interpretation and recommendations with different authority levels.
The dated inventory's task numbers describe its original delivery, not the revised
future task numbering.

The architecture phase will create:

- `docs/architecture/openspec-supervisor-target-architecture.md`;
- `docs/architecture/openspec-supervisor-target-architecture.ru.md`.

These future documents will contain the selected target and its decision record;
this change's `design.md` defines how to produce and assess them, not the chosen
runtime design itself. The roadmap will be a later, clearly marked section in the
architecture documents, added only after the readiness gate in decision 7.

EN/RU pairs must agree on scope, decisions, limits and validation. They are dated
planning/analysis deliverables outside the single maintained operator-guide
translation pair; do not expand or alter that manifest as a side effect.

Alternative: keep appending recommendations, final architecture and roadmap to the
original inventory. That obscures the inspected baseline and lets hypotheses appear
as current behavior. Separate linked records make the decision trail reviewable.

### 2. Synthesize sources through explicit decisions

For each material idea/control, the target architecture must record source/evidence,
current behavior or intention, adopt/adapt/defer/reject disposition, rationale,
architectural owner, invariant impact and any unresolved evidence dependency.
Coverage must include the inventory's C1–C12 responsibilities, installed OpenSpec
capabilities, original product intent and reconciled 2.0/2.1 backlog, plus the book
analysis. Explain contradictions rather than silently choosing the newest source.

The comparison must preserve the original purpose: sufficiently formalized product
requirements become executable work; bounded state-machine execution observes quota,
uses architecture reasoning when needed and escalates to the user at meaningful
intent/authority/tradeoff decisions. A mechanism survives because of its outcome,
not because a historical ticket or a book example names it.

Alternative: adopt every proposed mechanism. This would reproduce the duplication
and ceremony the inventory was created to identify.

### 3. Select architecture before selecting migration slices

Compare at least: adapting the existing controller, extracting a small executor
above OpenSpec, and building a replacement core/full rewrite. Assess simplicity,
implementation and operation cost, duplicate authority, quota efficiency, testability,
required invariant preservation, compatibility/recovery and evidence gaps. Select
one approach and state what observation would reverse that decision.

A thin executor is the current working hypothesis, not a predetermined outcome.
A replacement core is allowed as an architecture alternative; that does not imply a
big-bang cutover or rewriting every tested runtime safeguard. Code size alone is not
a rewrite justification. Do not construct an implementation sequence before this
comparison is complete.

The selected target must name component responsibilities/interfaces and data flow,
one source of truth per responsibility, minimal lifecycle versus blocked reasons,
durable state/receipt ownership, task identity under edit/rename/reorder/archive,
and crossings between planning, execution, runner and acceptance. Show how current
scope/quota/Git/checkpoint/audit/recovery behavior is retained or replaced, naming
the exact evidence required for replacement.

Alternative: let roadmap order determine the target implicitly. It commits to
interfaces and deletion assumptions before resolving their architecture.

### 4. Treat termination, context and acceptance as architectural contracts

The architecture must specify:

- one durable task budget covering implementation, architecture, diagnosis, repair
  and review across resume/restart/role changes, with reservation/consumption rules,
  enforcement limits and stop outcomes; budget is distinct from observed quota;
- progress/stagnation identity using relevant task content, checkpoint, failure
  signature and changed repair hypothesis, rather than resetting attempts on a new role;
- task-scoped context manifests, dependency-aware loading, input digests and applicable
  prompt/schema/policy/runner versions, plus invalidation and reuse conditions;
- mandatory acceptance versus authorized deferrable findings and new work, with
  stable issue identity/ownership/revisit conditions and no second editable backlog;
- selective fresh-context review using original requirements, diff and check evidence,
  with concrete findings and deterministic checks before additional model calls.

The user-selected review pattern is **Detail + Pragmatic** for both specification
and code review. It is an architectural requirement, not merely an optional alternative
to mention in the source comparison. Risk selects the depth and specialist lenses;
the architecture must define explicit review triggers and any bounded fast paths
without silently dropping either function from a triggered pair.

- **Detail** runs read-only in a fresh context, without the generator/implementer's
  conversation. For specs it checks coverage, contradictions, ambiguous behavior and
  contracts against source requirements and scope. For code it checks the exact diff,
  behavior, regressions and tests against the approved spec and verification evidence.
  Findings name stable IDs, artifact/content identity, location, requirement or risk,
  severity, evidence/counterexample and the consequence of leaving the issue unresolved.
- **Pragmatic** runs read-only in a separate fresh context with the same reviewed
  artifact/requirements, Detail's findings, verification evidence, scope, risk policy
  and remaining budget. It assesses whether another refinement is warranted and records
  an evidence-based disposition per finding: address now, defer within authority, or
  dismiss as unsupported/out of scope. It proposes accept, accept with authorized
  known issues, revise, or escalate; it cannot edit the artifact or grant authority.
- The controller applies mandatory requirements/checks and authority constraints
  before either recommendation. Supported unresolved blockers cannot be deferred or
  dismissed for speed; disputed critical findings require evidence-based resolution
  or escalation, not a majority vote, a score, or an automatic repeat of both critics.
  Budget exhaustion preserves work and stops; it never implies acceptance.
- Preserve both reports and all blocking findings; cap prioritized nonblocking advice
  without inventing a fixed number of issues. Count both roles against the same task
  budget, and invalidate/reuse reports only under explicit content/dependency identities.

The evaluation design must exercise spec and code pairs, including a real blocker,
optional polish, an unsupported finding, critic disagreement, changed inputs and
budget exhaustion. This selects review responsibilities; invocation implementation,
model selection and benchmark execution remain future work.

Exhausted budget is a stop, not success. Failed mandatory checks cannot be accepted
as Known Issues. Critic ratings and JSON validity do not establish truth. Book
thresholds and five-critic teams are not defaults; define how limits/review triggers
would be calibrated without forecasting quota or promising numerical savings.

Alternative: add independent local retries and a model score at each gate. It hides
total cost and allows repeated unchanged attempts to move between roles.

### 5. Define real authority and preserve transaction recovery

Role permissions must be enforceable through runner/tools/environment, including
shell and subprocess write channels. Distinguish read-only critic/diagnostic,
authorized implementation and controller-owned state/Git authority. Define the
behavior when an intended boundary cannot be enforced; do not silently claim it.
Ordinary authorized tests may evolve with implementation; independent acceptance
checks must be protected against weakening to manufacture success.

Retain explicit grants, one writer, immutable engine identity where required,
durable quota authorization, checkpoint identity, deterministic verification, Git
transactionality, duplicate-side-effect prevention, audit and recovery evidence.
File existence alone is not a completion/checkpoint proof. The target must cover
interruptions around consumption, invocation, report persistence, checks, commit
and push, including repeated resume and stale input. Human authority remains distinct
from model advice and artifact readiness.

Alternative: rely on prompt prohibitions, post-run diff checks or the book's simple
file-existence resume. Those cannot provide the same prevention/recovery guarantees.

### 6. Specify the evaluation, without running it in this change

Map required invariants and failure trajectories to existing tests and missing
acceptance evidence. Define a bounded OpenSpec-task experiment including successful
completion, interruption, verification failure and repeated resume. Specify fixtures,
input/version identity, limits, checks, comparable baseline and decision criteria.

Compare accepted outcomes, total/role call counts, repeated failure signatures,
active time, human intervention and duplicate side effects. Record unknown usage and
runtime evidence explicitly; do not invent savings or treat critics' scores as the
primary quality measure. Existing source-based inventory is not a live benchmark.
Implementation and execution of the experiment belong to a separate approved change.

Alternative: choose the rewrite from a diagram or a self-assigned quality score.
That does not test the expensive failure/recovery paths.

### 7. Make architecture readiness a prerequisite for roadmap construction

Before any roadmap authoring, finish the target architecture, check source coverage,
interfaces, ownership, lifecycle, controls and EN/RU agreement, and resolve all choices
that would alter component boundaries, authority, required acceptance or implementation
structure. The architecture must contain the selected alternative and a readiness
record naming the reviewed document revision/content identity, checks, material
decisions and their provenance.

Material user-owned decisions follow the existing escalation model; ordinary local
reversible architecture choices do not require a new blanket approval ceremony.
Nonblocking evidence gaps may remain explicit if the chosen boundary is still sound
and the roadmap can isolate the affected slice. Unresolved architecture-blocking
choices keep roadmap tasks pending; a plausible diagram is not completion.

Only then derive small dependency-ordered migration slices, acceptance/deletion
criteria, preserved evidence and rollback points, each linked to selected architectural
contracts. Favor an incremental transition even if a new core is chosen. No removal
is recommended without replacement coverage and applicable retention decisions.

Alternative: write architecture and roadmap simultaneously. That invites roadmap
assumptions to bypass unresolved architectural choices.

## Risks / Trade-offs

- **Book authority or unverified claims override evidence** → Preserve source identity,
  page references, caveats and explicit source-to-decision dispositions.
- **Thin-executor confirmation bias** → Compare adaptation, extraction and replacement;
  state falsification/acceptance evidence for the selected option.
- **New architecture adds another planning layer** → Assign exactly one owner per
  fact and reject components/artifacts without a necessary outcome.
- **Good Enough weakens acceptance** → Blocking mandatory conditions cannot become
  deferred issues; budget exhaustion is a separate stop outcome.
- **Local limits hide unbounded total cost** → Task-wide durable accounting includes
  every role and restart; resource enforcement limits remain visible.
- **Permissions exist only in prose** → Specify enforcement over all available write
  channels and explicit behavior when the required boundary is unavailable.
- **Rewrite discards tested recovery** → Require invariant/test mapping and a bounded
  future comparison before replacement is considered proven.
- **Roadmap starts from unfinished architecture** → Explicit readiness prerequisite
  with content identity and resolved blocking choices.
- **Private context leaks through evidence** → Use tracked/redacted sources; do not
  copy ignored runtime histories, managed-project content or the supplied PDF.

## Migration Plan

This documentation change has no runtime deployment. Save the analysis, construct
and validate the target architecture, then derive its roadmap and validate the
complete assessment. Rejected recommendations can be revised without controller
rollback. Accepted implementation slices require separate changes with their own
scope, authority, qualification and rollback; this change does not execute them.

## Open Questions

Only deferrable evidence gaps belong here. Architectural choices such as component
boundaries, state ownership, task identity, permission enforcement and the integration
interface are mandatory outputs of group 5, not questions left for the roadmap.

- Which redacted runtime aggregates, if later authorized, can support calibration
  beyond static source evidence? Their absence does not prevent a bounded initial
  evaluation design with explicitly unknown real-world economics.
- Which historical recovery records still require retention? Keep affected legacy
  paths unresolved until evidence is available; never silently delete them.
