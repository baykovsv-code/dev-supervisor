# Harness Engineering: implications for Development Supervisor

Date: 2026-11-18. Repository reference: `4768d05f0d6f31893ea3d857cb7d8a68d01c8f57`.
[Russian counterpart](harness-engineering-analysis.ru.md).

Status: saved analysis and architectural recommendations. The user requested that
these findings inform architecture before a migration roadmap is constructed. This
record does not select or implement the final architecture, authorize a rewrite, or
supply a migration roadmap.

## 1. Sources and limits

The supplied local book is **Harness Engineering — Пайплайны для создания спеки с
критиками**, 349 PDF pages, dated 2026-06-14 on its cover. Source location at review:
`~/Downloads/Harness Engineering.pdf`. SHA-256:
`b81fc0076b93fe86916221fe31909b4f4be24aa7de6a479a64c6bc43a482cdb7`.
Page references below use the PDF page numbers. The book is not copied into the
repository and is not an authority for changing project behavior.

The review focused on chapters 4–7, 9, 11–12, 16 and 18, with additional inspection
of the role split, autonomy and economics material. It is a source-based architectural
analysis, not an independent reproduction of the book's experiments or a verification
of current provider features, model identifiers, prices or claimed savings.

Project evidence: the [AS-IS inventory](as-is-openspec-inventory.md), its
[structural manifest](as-is-openspec-evidence.json), [current operator guide](../operator-guide.md),
[2.1 candidate](../backlog/supervisor-2.1.md), and tracked controller/tests. The
[September discussion](../dev-supervisor-discussion-2026-09-25.md) and completed 2.0
architecture are historical intent, reconciled by the inventory. The book primarily
addresses specification generation; its mechanisms need adaptation to code execution.

**Conclusion:** retain the useful runtime safeguards, reconsider the planning and
attempt-management architecture, and use measured evidence to choose between
incremental extraction and a replacement executor. The book does not establish that
a complete rewrite is preferable.

## 2. Useful ideas and their adaptation

| Book mechanism | Supervisor relevance and proposed adaptation |
|---|---|
| Good Enough gate; chapter 7, pp. 102–116 | Separate mandatory acceptance from optional improvements. Finish when required behavior and checks are satisfied; do not iterate to maximize a critic's score |
| Hard iteration limits; chapters 7 and 11 | Apply one durable task budget across implementation, architecture, diagnosis, repair and review, including resume and role changes |
| Fresh-context critic; chapter 6, pp. 86–99 | Review requirements, exact diff and verification evidence independently of the implementer's conversational justification |
| Detail + Pragmatic; chapter 7, section 7.4.6, pp. 109–110 | Use two distinct review functions for specs and code: find defects, then assess which findings justify refinement or authorized deferral |
| Progressive disclosure; chapter 5, pp. 66–83 | Assemble explicit task-scoped context with identities/digests rather than a broad repeated documentation bundle |
| Simplicity critic; chapter 4, pp. 51–65 | Require each state, approval, artifact, component and model pass to justify a failure mode or necessary outcome; compare simpler alternatives |
| Enforced permissions; chapter 12, pp. 201–222 | Give roles actual tool/filesystem authority appropriate to their work; post-run diff checks supplement prevention |
| Planner/generator/evaluator split; chapter 10 | Separate planning content, bounded execution and acceptance evidence; use selective reviews instead of permanent teams of critics |
| Operational metrics; chapters 11 and 18 | Measure accepted results, repeated failures, calls, time and human intervention; self-evaluation scores alone cannot establish effectiveness |

### 2.1 One termination mechanism for the whole task

Current code has a model-process watchdog, observed-quota authorization and escalation
after repeated implementation recoveries. `_maybe_trigger_diagnostic` is a threshold
for another role, not a total task budget. A chain of implementation → recovery →
diagnostic → repair → diagnostic can consume calls while satisfying each local rule.

Proposed architecture requirements: durable limits for total calls, active time and
attempts against the same cause, covering every role and restart. Exhaustion preserves
the current result and stops with an actionable reason; it never marks the task
successful. Budgets remain distinct from quota permission: available quota does not
justify unlimited attempts, and a task budget does not authorize unavailable quota.

Each new repair attempt should record a changed hypothesis: what changed since the
previous failure and why another call could help. The same checkpoint, failure
signature and repair hypothesis should not trigger another automatic attempt.
Exact limits require calibration. The book's example counts are not project defaults.
Actual usage accounting is not quota forecasting; hard resource ceilings require
runner-level enforcement and reserved allowance, not just checking spend after a call.

### 2.2 Good Enough based on acceptance, not model ratings

Classify findings into:

- **Blocking:** violated requirements, failed mandatory verification, unresolved
  authority or material data-safety risk. The task cannot complete.
- **Deferrable:** an improvement outside mandatory acceptance whose deferral is
  consistent with the approved scope and risk authority.
- **New work:** a useful change requiring a separate scope decision/change.

Example: a working, verified export should not automatically enter another architecture
cycle because a critic suggests a background-job queue. Unmet mandatory acceptance
must never be reclassified as Known Issues to obtain a pass. Deferred findings need
stable identities, ownership, rationale and a revisit trigger, linked to OpenSpec or
the existing backlog rather than another independent planning registry. Creating
external tracker issues is not implied or authorized by this recommendation.

### 2.3 Selective independent review

The normal successful path validates the implementation report and runs deterministic
checks; architecture review principally handles blockers. An independent acceptance
review is a different function. Its inputs should be original requirements, exact diff,
check results and material constraints, not the implementer's prior conversation.
Findings should identify a location, violated requirement and consequence, with a
checkable counterexample where possible. A critic's assertion is a finding to assess,
not authority to change scope or permissions.

Choose review perspectives from risk: contracts/state, security, scenario coverage,
or unnecessary complexity. Use ordinary validators for mechanical properties. A
standing team of five critics would add cost without evidence of proportional value.
Cache/reuse reviews only while the reviewed inputs and relevant dependencies match;
whole-system integration checks still matter when local reviews miss interactions.

### 2.3.1 Detail + Pragmatic for specification and code review

User decision (2026-11-18): include this pair for both kinds of review as a required
part of the future architecture. This refines the earlier selective-review
recommendation; implementation and concrete review triggers remain future design work.
Risk selects review depth/specialist lenses and explicit fast paths, not an unrecorded
omission of one function from a triggered pair.

**Detail** independently finds concrete defects in a fresh read-only context. For a
specification, it checks source requirement coverage, contradictions, ambiguity,
contracts and missing behavior within scope. For code, it checks the exact diff,
behavior, regressions and tests against the approved spec and check evidence. Each
finding records a stable ID, reviewed content identity, location, requirement/risk,
severity, evidence or counterexample, and consequence.

**Pragmatic** receives the same reviewed artifact and requirements, Detail's findings,
verification evidence, scope, risk policy and remaining budget in a separate fresh
read-only context. It judges whether further work is worthwhile and assigns a reasoned
disposition to every finding: address now, defer within authority, or dismiss as
unsupported/out of scope. Its recommendation is accept, accept with authorized known
issues, revise, or escalate. Neither critic edits the artifact or grants authority.

Mandatory requirements, checks and permissions take precedence over recommendations.
A supported unresolved blocker cannot be waived for speed. Disputed critical findings
require evidence-based resolution or escalation; model ratings, majority voting and
repeating identical reviews do not resolve them. Exhausted budget means a preserved
stop, not acceptance. Keep both reports and all blockers; limit only prioritized
nonblocking advice, without requiring critics to invent a fixed number of findings.
Count both roles within the task-wide budget and bind reuse/invalidation to reviewed
content and dependencies. Evaluation must include real blockers, optional polish,
unsupported findings, disagreement, changed input and budget exhaustion for both
spec and code review. No critic calls are launched by this documentation decision.

### 2.4 Context as an explicit invocation contract

`Supervisor._prompt` already supplies ticket text, authoritative-document paths and
recovery context, but contains many special cases. A proposed context manifest should
name the task and acceptance, relevant requirements/decisions, allowed changes,
mandatory checks, checkpoint and recovery hypothesis, with input identities/digests
and applicable prompt/schema/policy/runner versions.

This makes a fresh invocation reproducible and allows preflight, comparison and
invalidation of stale work. Stable OpenSpec references and dependency-aware loading
are a reasonable starting point. A vector database, generic memory service or new
planning hierarchy is not justified by this analysis. Context minimization must not
omit cross-component invariants or permissions.

### 2.5 Authority enforced before side effects

`CodexRunner.invoke` uses `--sandbox workspace-write` for the roles; its command does
not show role-specific filesystem permissions. Some role restrictions are expressed
in prompts and checked after execution. The book's useful lesson is to enforce the
boundary at the tool/environment layer as well.

Candidate roles: critic/diagnostic read only; implementation writes the authorized
task scope; protected-contract changes require appropriate authority; the controller
owns its state and Git transaction. All write channels, including shell/subprocesses,
must respect the boundary; restricting one write tool is insufficient. Inability to
enforce a promised boundary must stop or select an explicitly permitted weaker mode,
not silently claim isolation. Exact enforcement mechanisms need architecture design.

Do not copy a blanket ban on changing tests. Ordinary tests evolve with authorized
implementation. Protect independent acceptance checks from being weakened to obtain
a pass. Review annotations and sentinel markers are not enforcement by themselves.

### 2.6 Evaluate the harness itself

Existing fault/regression tests are valuable acceptance evidence for a successor,
not just implementation details of the old controller. Compare representative tasks
and failure trajectories using accepted outcomes, calls per result, repeated failure
signatures, active time, human interventions, and duplicate side effects. Bind runs
to model/prompt/policy/context versions; report unavailable usage rather than infer it.

A decisive bounded experiment would execute one OpenSpec task through normal completion,
interruption, failed verification and repeated resume. Define its acceptance and
resource limits in the architecture; implement and run it only in a separately
scoped execution change. This analysis does not establish an experimental result.

## 3. Where the book must not be copied literally

- Page 305 demonstrates resume by file existence. That is inadequate for Supervisor:
  it does not establish input identity, successful completion, content integrity or
  committed side effects. Existing checkpoint/Git/authorization reconciliation is
  stronger and should be preserved or demonstrably replaced.
- A valid structured JSON response proves shape, not truth or objective quality.
  Numerical ratings and agreement between critics do not replace acceptance evidence.
- Score thresholds, fixed iteration counts, coverage percentages, model routing,
  caching economics and claimed performance gains require project-specific evidence;
  this analysis does not validate them as universal facts.
- More model roles, a model acting as every gate, or recurring supervisor-model calls
  can increase overhead. Deterministic checks and risk-triggered review take priority.
- Tool annotations, path-name heuristics and one restricted file tool are not complete
  controls when another tool can write. Read-only/writable authority must cover all
  available channels and relevant descendants.
- The chapter 18 report (pp. 346–349) states roughly 316 agent launches and 9–10 million
  tokens for the book, with most chapters reaching the refinement cap. These are
  author-reported figures, not independently reproduced evidence or a controlled
  comparison. They illustrate expense and stopping needs, not a guarantee of savings.

## 4. Candidate architecture and the rewrite decision

The following is a hypothesis to evaluate, not the final target design:

```text
OpenSpec: requirements / design / task content
                     |
                     v
Supervisor: selection / context / budget / policy
                     |
                     v
Runner: bounded agent execution
                     |
                     v
Acceptance: checks / scope / checkpoint / Git
                     |
               result or stop
```

The components are responsibility boundaries, not a mandate for separate services,
a plugin framework, a generic DAG engine or a specific number of modules. Planning
content can move to OpenSpec while tested quota, checkpoint, Git and recovery behavior
is retained. State-machine redesign must distinguish lifecycle from blocked reasons
and avoid a new bespoke state family for every exceptional history.

| Alternative | Assessment to carry into architecture |
|---|---|
| Add critics/states to the current monolith | Can add capability but may compound current special cases; justify before selecting |
| Extract a small executor over OpenSpec | Preferred working hypothesis: test useful simplification while preserving invariants |
| Build a replacement core or rewrite | Legitimate alternative if safe extraction is harder; must demonstrate equivalent required guarantees and evidence, not rely on source size alone |

The future architecture must compare these alternatives, select and explain one,
map retained/replaced behavior and define what evidence would reverse the decision.
An independent replacement executor is not automatically a rewrite of every tested
mechanism; a choice of implementation structure is distinct from a big-bang cutover.

## 5. Required architecture work before the roadmap

Synthesize the inventory, installed OpenSpec capability evidence, this analysis,
current operator contracts/tests, and reconciled 2.0/2.1 intent. For each material
idea record adopt/adapt/defer/reject, source, reason, invariant impact and architectural
owner; retain strong existing mechanisms even when the book offers simpler examples.

The target architecture needs component/interface and source-of-truth contracts;
minimal lifecycle and durable state ownership; stable task/context identity; budgets
and progress/stagnation; acceptance/deferred-issue semantics; Detail + Pragmatic
review for specs and code with explicit triggers;
enforced role authority; Git/quota/recovery behavior; and an evaluation design.
Resolve architecture-blocking choices there, escalating only material user-owned
product/authority/tradeoff decisions under the existing decision model. Do not add
an approval request for each local architecture choice.

Only after that architecture is coherent and its blocking choices are resolved
should roadmap tasks derive implementation slices, deletion criteria and rollback
points. A roadmap must reference the selected architecture, not make the architecture
implicitly through its task order. No target-architecture implementation or benchmark
run is authorized by this documentation update.
