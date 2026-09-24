# Supervisor 2.0 proposed architecture baseline

Status: **PROPOSED — human approval required before T01**.

## Purpose

Evolve the preserved standalone 1.x supervisor into a minimal 2.0 controller that can
admit existing projects safely, complete and renew plans, control mutation and push
authority explicitly, and upgrade without two controller generations writing the same
project.

The first commit in this repository is an AS-IS extraction, not a partial 2.0
implementation. The 1.x behavior and tests remain the executable compatibility
baseline until an approved ticket intentionally changes them.

## Boundaries

The system retains four explicit boundaries:

1. **Engine repository** — controller code, prompts, schemas, tests, and operator
   documentation.
2. **Managed repository** — product code, approved architecture, plan/tickets, a small
   launcher, and project policy.
3. **Host-local runtime** — state, quota observations, locks, run evidence, effective
   host capability grants, and secrets. It is ignored by Git.
4. **Canonical remote** — optional persistence target. It is not a lock service and has
   no authority while push is disabled.

The engine operates as a single local process. A module split is allowed only when a
ticket proves that it reduces state-machine, schema, or test risk; packaging, plugins,
and services are non-goals.

## Authority and configuration

Configuration is versioned and schema validated. Ordinary project configuration may
lower permissions. Security-sensitive enabling grants live in operator-controlled
host configuration (or an equivalent explicitly approved external authority) and are
combined by intersection. Therefore a pulled commit cannot enable its own mutation or
push.

The effective configuration reports provenance and redacts secrets. Unknown keys,
invalid values, contradictory thresholds, missing grants, and unsupported versions
fail before a model process or remote mutation starts.

Initial independent capabilities are:

- `self_modification` — repair or development of the active product when that product
  is Supervisor;
- `user_requested_modification` — work introduced outside the currently approved
  implementation plan;
- `repository_push` — any update of a remote ref.

All default to disabled. Enabling one does not imply another. Approved-ticket local
implementation and local commit remain separate permissions.

## Lifecycle

The persisted lifecycle separates discovery, decisions, planning, execution, and
completion:

```text
ASSESSMENT
  -> REQUIREMENTS_REVIEW
  -> ARCHITECTURE_REVIEW
  -> PLAN_READY
  -> TICKET_READY/RUNNING/VERIFYING/COMMITTING
  -> PLAN_COMPLETED
  -> BACKLOG_REVIEW
  -> REQUIREMENTS_REVIEW (new epoch)
```

Every approval names exact document versions. A material change invalidates the
affected approval. The last ticket commit and plan completion are reconciled
idempotently across crashes. `PLAN_COMPLETED` never starts another model by itself.

A backlog item becomes executable only after bounded selection, requirements and
dependency analysis, architecture impact review, human approval, and creation of a
new immutable plan epoch. Prior epochs and their evidence remain addressable.

## Existing-project admission

Assessment is read-only with respect to product code. It records observable repository
facts and labels inferences. Scenario A returns an external-architecture requirement
and a finite admission checklist. Scenario B returns compatibility findings and a
mapping/gap manifest. Neither path changes Supervisor to fit the project. A
Supervisor-compatible index is generated only from an approved baseline and preserves
source document/identifier lineage.

## Execution and Git persistence

The existing deterministic sequence remains the starting point: immutable starting
HEAD, bounded model run, structured report, configured checks, exact scope validation,
local commit, and durable state reconciliation.

Push is a later, separately authorized state after local commit. When disabled, status
is `LOCALLY_COMMITTED`; no remote command is attempted. When enabled, the configured
remote and branch are validated, only the verified commit may be pushed, and remote
reachability is confirmed before `REMOTELY_PERSISTED`. Interrupted confirmation is
idempotent. Normal operation never force-pushes or rewrites history.

## Quota

Quota decisions use current trusted observations only. High observations may authorize
a bounded number of calls within a TTL; medium observations require a fresh snapshot
per call; low or unknown observations block. Every call has a durable authorization
record. No future quota, reset-time, ticket-capacity, or consumption forecast is
computed. `forecast.fallback_ticket_hours` has no 2.0 schema or migration mapping.

## Engine versions and multiple hosts

Each runtime binding names an immutable engine identity and compatible config/state/
protocol ranges, not only a path. Updates are fetched into a separate version location,
verified, migration-dry-run, and tested without touching the active controller. The
switch occurs only after quiescence and archive creation, followed by read-only
reconciliation and explicit go/no-go. Rollback first stops the new generation.

A stale host that encounters a newer required engine or state version stops without
writing. A single writer lease or explicit host ownership is required when the same
managed project is visible from multiple computers. Git branches and local locks are
insufficient distributed ownership evidence.

## Self-development

The generation performing a run is immutable. An enabled self-development workflow
produces and verifies a successor generation in an isolated checkout. Activation is a
separate quiescent cutover with human approval and rollback material. The successor
cannot grant itself capabilities, alter the active controller in place, or control the
same managed project concurrently.

## Migration from 1.x

The migration accepts only explicitly supported quiescent states. It archives the
exact 1.x engine revision, policy, state, quota ledger, artifacts, lock ownership, and
product fingerprint. A dry-run conversion produces a report before any binding change.
The cutover preserves product HEAD and working tree, atomically changes binding, runs
read-only reconciliation, and requires human go/no-go. Unsupported or ambiguous state
stops; it is never guessed.

For the current extraction, `personal-assistant` remains at its existing T30
`HUMAN_GATE`. Copying the byte-identical AS-IS engine into this repository repairs its
initial path binding without converting product state. Before T00, the live project is
rebound to a separate detached AS-IS checkout at extraction commit `41f6757`; the
development checkout is no longer executable authority for that project.

## Rolling compatibility and activation

Compatibility is a completion gate for every implementation ticket through T11 in
authoritative plan order, including an inserted prerequisite, not a T12-only activity.
T00 creates a redacted, checksummed fixture from the real T30 `HUMAN_GATE` policy and
runtime shape plus a deterministic no-model harness. All subsequent ticket verification
runs that harness.

For every candidate revision the harness must prove:

- the existing launcher CLI and path-only legacy binding remain readable;
- the current project policy and T30 state can be loaded without implicit conversion;
- `status` and a no-model reconciliation/resume preserve the state bytes;
- no product file, product HEAD/fingerprint, quota authorization, gate, or run evidence
  changes;
- a schema-changing ticket supplies its compatibility reader, explicit dry-run
  migration, rejection behavior, and rollback in that same ticket.

This is candidate compatibility, not live activation. The live project remains on the
detached AS-IS engine until implementation through T11 is complete. Intermediate
revisions are exercised only on isolated repository/runtime copies. T12 performs the
full integration rehearsal; the post-T12 human gate is the first point at which the
live binding may change. Thus old and new development can proceed without hot-changing
the controller used by the live T30 gate.

## Verification strategy

- preserve and run the complete 1.x unit suite at the extraction baseline;
- run the T00 personal-assistant compatibility harness after every implementation
  ticket;
- stop an unchanged generic `VERIFICATION_FAILED` checkpoint from rerunning the same
  check; an explicit audited recovery action must first validate the exact model
  checkpoint, exactly one currently configured failed check, and its durable log, then
  open bounded same-ticket repair without itself consuming quota or invoking a model;
- keep mandatory host-verification failures on their stricter existing reconciliation
  path, and after any repair rerun the full verification suite followed by the ordinary
  scope and commit gates;
- add schema and transition tests for every new state and capability;
- inject crashes before and after each durable write, commit, push, and binding switch;
- test denial paths as first-class behavior;
- qualify migration and rollback on an isolated copy of real `personal-assistant`
  state before live cutover;
- keep manual owner gates for real credentials, browser/account evidence, and final
  go/no-go decisions.

## Human gate

Approval must confirm this document, the requirements index, implementation plan, and
ticket boundaries together. Before approval, only read-only `./dev status` checks are
authorized in this repository. No quota should be supplied and no model run should be
started. T00 is the first executable ticket; T01 cannot start until T00 has established
and verified the isolation/compatibility gate.
