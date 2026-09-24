# Supervisor 2.0 requirements index

Status: **proposed input to the human architecture gate**. This document normalizes
the backlog into stable identifiers. It does not authorize implementation by itself.

## Source lineage

- Development Supervisor 1.x code at
  `854083f51c9aedf33ec2d9654fc67aacff84af8a`;
- Russian AS-IS documents under `docs/*.ru.md`;
- Russian Supervisor 2.0 backlog in the legacy repository at
  `docs/backlog/supervisor-2-requirements-ru.md`;
- the pre-existing GitHub persistence requirement in `BACKLOG.md`.

The Russian source remains historical input. All new authoritative 2.0 documents are
English.

## Requirements

| ID | Requirement | Mandatory outcome |
|---|---|---|
| R01 | Cold start from a user specification | Preserve the source specification, iterate requirements and architecture through explicit human approval, and create no implementation plan or product delta before approval. |
| R02 | Minimal sufficient architecture | Record the simpler alternative, selected design, complexity cost, non-goals, and approval for any complexity-budget exception. |
| R03 | Existing repository without architecture documents | Perform a shallow read-only inventory, recommend an independent external architecture stage, return minimum admission requirements, and create a compatible plan/index only after reviewed documents pass revalidation. |
| R04 | Existing repository with foreign-format documents | Produce compatible/conditionally-compatible/incompatible findings; never adapt Supervisor to one project outside its own approved change cycle; create a mapped plan/index only after the user fixes and approves the source documents. |
| R05 | Development after the original plan | Complete the final ticket transactionally, enter `PLAN_COMPLETED`, select bounded backlog work, perform architecture review, and create a new versioned plan epoch before implementation. |
| R06 | Mutation capability controls | Independently control self-modification and user-requested out-of-plan modification. Both default to disabled, fail closed, and cannot be enabled by repository content or prompts. |
| R07 | Push capability and persistence | `git push` defaults to disabled. When explicitly enabled, completion requires exact-commit remote confirmation, idempotent recovery, protected-history safety, credential redaction, and audit evidence. |
| R08 | Safe multi-host engine updates | Pin immutable engine identities, stage and qualify updates away from the active controller, switch only at quiescent checkpoints, reject incompatible state, and retain rollback without dual control. |
| R09 | Quota policy | Use configurable high/medium/low observed ranges, TTL and bounded reuse, fail closed on missing data, and audit every invocation. Do not predict future quota. |
| R10 | Versioned configuration contract | Move operator-controlled thresholds and capabilities into validated documented configuration; reject unknown, contradictory, or out-of-range values and expose effective redacted configuration. |
| R11 | User-requested bounded improvements | Require an explicit trigger, architecture impact review, iterative correction, approval, bounded plan/ticket, verification, and escalation to a normal cycle when bounds are exceeded. |
| R12 | Self-development | Apply the ordinary requirements/architecture/plan/check workflow plus immutable-controller handoff; never edit the controller generation executing the run. |
| R13 | English 2.0 documentation | Requirements, architecture, ADRs, plans, tickets, policies, runbooks, reports, and templates created for 2.0 are English. Russian 1.x material remains an unmodified archive. |
| R14 | Remove dead forecast behavior | Do not implement or migrate `forecast.fallback_ticket_hours`; do not implement or migrate quota forecasting. Current trusted quota observations and guards remain required. |
| R15 | 1.x to 2.0 cutover | Provide versioned schemas, dry-run conversion, checksummed predecessor archive, exact HEAD/fingerprint preservation, one controller/lock authority, qualification on a copy, and rehearsed rollback. |
| R16 | AS-IS behavioral preservation | The initial extraction into this repository must remain byte-equivalent for engine-owned runtime files and pass the complete 1.x regression suite before any 2.0 change. |
| R17 | Rolling personal-assistant compatibility | Every T00–T11 candidate must pass a no-model compatibility harness against a redacted real T30 policy/state fixture. Live personal-assistant remains on an immutable AS-IS checkout until T12 and the final human cutover gate. |

## Cross-cutting invariants

1. One managed repository has exactly one active writer/controller.
2. Model output is never authority for enabling a capability or approving architecture.
3. Unknown configuration, version, state, ownership, or migration semantics fail closed.
4. A controller revision is immutable for the duration of a run.
5. Git synchronization is persistence, not a distributed runtime lock.
6. Backlog items are not executable tickets until architecture and planning gates pass.
7. Migration and rollback do not change the managed product HEAD or working tree.
8. A ticket is not complete if the candidate cannot safely inspect and reconcile the
   approved legacy `personal-assistant` fixture without a model or state mutation.

## Deliberate exclusions

- no general ALM, plugin, or distributed-compute platform;
- no automatic reconstruction of authoritative architecture from code;
- no force-push or history rewrite in the normal workflow;
- no hot reload of controller code;
- no quota prediction;
- no compatibility shim for `forecast.fallback_ticket_hours`.
