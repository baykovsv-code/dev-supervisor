# Supervisor AS-IS inventory and OpenSpec comparison

Assessment date: 2026-11-18. Inspected commit:
`07bb23209aa5141fd1d2b606c06c852bdc2b8e7f` (clean `main` before this assessment).
English assessment; [Russian counterpart](as-is-openspec-inventory.ru.md).

**Finding:** Supervisor combines a planning system with a host-local execution
controller. OpenSpec can own much of the first responsibility; the inspected
OpenSpec interfaces do not replace the second. Keeping both planning representations
as independent authorities would preserve duplication and introduce drift.

This is an assessment and a candidate operating model, not an approved behavioral
specification. At the user's requested stopping point it covers change tasks 1–4;
there is deliberately no incremental migration roadmap, removal schedule, or migration
review checklist (task group 5). The complete-assessment gate 6.1 remains pending.
No controller, policy, schema, runtime, or managed-project behavior changes here.

## 1. Baseline and evidence rules

Evidence priority: tracked executable code and tests for implemented behavior;
current English operator documentation for the operating contract; historical
architecture and discussion for intent only. A test name indicates coverage, not
proof that a live deployment has exercised the path. Recommendations below are
explicitly prospective and grant no authority.

The [structural evidence manifest](as-is-openspec-evidence.json) records tracked
source paths, SHA-256 digests, line counts, schema required fields, test names,
parser nodes, and literal state constants at the inspected commit. Generated
`.agents/skills/` workflows were inspected separately. Reproduce measurements with
`git ls-files`, Python `ast.parse` on `supervisor.py` and `tests/test_*.py`, and
`len(Path(path).read_text().splitlines())`. Counts below use physical lines,
including blanks; parser nodes count `add_parser` calls, not valid command combinations.

Ignored `.dev-supervisor/`, account data, run logs, external managed repositories,
and secrets were neither inventoried nor copied. The tracked project policy was
examined structurally; its private/contextual values are not reproduced. This means
actual run frequency, quota cost, production incident rates, host qualification,
and release completion cannot be established from this assessment.

Installed CLI: `openspec --version` → **1.14.3**. Package workflow:
`spec-driven`, schema version **1** (`openspec schema which spec-driven --json`,
then read the resolved `schema.yaml`). Generated skills declare `generatedBy:
1.14.3`; the tracked file content, rather than that label alone, was inspected.
`openspec list --json` resolves this repository as `nearest`; no store is declared
in [config](../../openspec/config.yaml). There are no main specs, one active change,
and no archived changes beyond `.gitkeep`. Planning artifact completion reported by
`status` is distinct from implementation task completion reported by `instructions apply`.

Version-matched upstream references: [workflow guide](https://github.com/Fission-AI/OpenSpec/blob/v1.14.3/docs/workflows.md)
and [CLI reference](https://github.com/Fission-AI/OpenSpec/blob/v1.14.3/docs/cli.md).
These describe assistant-driven actions and CLI support; local command results and
installed schema/skills below are the detailed evidence for this installation.

## 2. Component and responsibility inventory

Rows C1–C12 are the coverage units used by the ownership matrix. The evidence
manifest enumerates every tracked file within these units, including individual
schemas and tests; grouping does not imply identical retention decisions.

| Unit | Components and responsibility | Executable/document evidence |
|---|---|---|
| C1 | `supervisor`, `dev`, initialization: engine entry point, bound launcher, control-file/scaffold creation | [engine](../../supervisor.py): `initialize_repository`, `project_launcher_text`; [launcher](../../dev); [entry point](../../supervisor) |
| C2 | Policy/configuration and capabilities: validate project restrictions, combine with host grants, expose redacted effective settings | `validate_project_policy`, `load_host_capability_grants`, `Supervisor.__init__`, `effective_configuration`; [tracked policy](../../dev-supervisor.json); [policy tests](../../tests/test_policy_contract.py) |
| C3 | Planning: cold start, admission, backlog cycles, immutable epochs, insertion amendments, explicit improvements | `AdmissionReview`, `begin_cold_start`, `materialize_cold_start_plan`, `materialize_backlog_epoch`, `apply_insertion_plan_amendment`, `materialize_improvement_plan`; [improvement tests](../../tests/test_controlled_improvement.py) |
| C4 | Runtime coordination: state load/save, single-writer locks, run/resume/stop, dashboard and timing | `operation_lock`, `initial_state`, `load_state`, `transition`, `_run_loop`, `resume`, `request_stop`, `dashboard`; [main tests](../../tests/test_supervisor.py) |
| C5 | Quota: manual observations, per-role validation, TTL/reuse, durable authorization, ledger conversion | `QuotaProvider`, `ManualQuotaProvider`, `_guard_quota`; [quota tests](../../tests/test_observed_quota_policy.py) |
| C6 | Model execution and reports: CLI runner, watchdog, structured outputs, diagnosis and bounded engine repair | `CodexRunner`, `run_process_with_watchdog`, `validate_report`, `_invoke`, `_invoke_diagnostic`, `_invoke_supervisor_repair` |
| C7 | Verification, scope, Git transaction and checkpoint recovery | `_run_verification`, `_scope_gate`, `_prepare_commit`, `_finish_commit`, `_reconcile_push`, `recover_generic_verification_failure`, `recover_protected_snapshot` |
| C8 | Engine identity, host ownership, upgrades and legacy/state migration | `_assert_engine_binding`, `_assert_writer_lease`, `activate_engine_update`, `apply_state_migration`, `apply_legacy_cutover`, `apply_later_scope_recovery` |
| C9 | 19 schema files: reports; approval/admission/cold-start/backlog/improvement/epoch contracts; audit; policy; host grants/owner; engine identity/binding; state versions | [schema manifest](as-is-openspec-evidence.json); e.g. [policy](../../schemas/project-policy-v2.schema.json), [state](../../schemas/supervisor-state-v7.schema.json) |
| C10 | Eight prompts: `implement`, `architecture-blocker`, `diagnose`, `supervisor-repair`, `cold-start-review`, `existing-project-admission`, `backlog-cycle-review`, `improvement-review` | [implementation](../../prompts/implement.md), [architecture](../../prompts/architecture-blocker.md), [diagnosis](../../prompts/diagnose.md); all eight enumerated in manifest |
| C11 | Five test modules, legacy cutover policy/quota and reference-policy fixtures, documentation check script | [main](../../tests/test_supervisor.py), [policy](../../tests/test_policy_contract.py), [quota](../../tests/test_observed_quota_policy.py), [improvements](../../tests/test_controlled_improvement.py), [documentation](../../tests/test_documentation_governance.py), [checker](../../scripts/check_documentation.py) |
| C12 | Current operator contract and backlog; historical requirements/architecture/plan/tickets/migration analysis; OpenSpec planning and generated workflows | [guide](../operator-guide.md), [governance](../documentation-governance.md), [2.1 backlog](../backlog/supervisor-2.1.md), [historical requirements](requirements-index.md), [historical plan](implementation-plan.md), [migration analysis](migration-analysis.md), [change proposal](../../openspec/changes/inventory-as-is-for-openspec-evolution/proposal.md) |

Schema caveats: `project-policy-v2.schema.json` actually titles/declares **v3**;
state v5/v6 files coexist with runtime v7, host grant v1 with v2. File names alone
are unreliable version evidence. JSON schemas are not the entire validator:
`validate_project_policy`, report validators, state/epoch and checkpoint predicates
contain additional semantics. Several schemas allow generic objects or an unrestricted
phase string; schema validity alone cannot establish a safe transition.

## 3. AS-IS lifecycle, storage and decisions

Ordinary path (`_run_loop`, `_process_invocation`, `_finish_commit`):

```text
READY → quota guard + consume → IMPLEMENTING → report validation
  pass → VERIFYING → SCOPE_PENDING → COMMITTING → [PUSHING] → next READY
                                                          → PLAN_COMPLETED
  ambiguity/deviation → ARCHITECTURE_PENDING → ARCHITECTURE_REVIEW
  product decision → HUMAN_GATE
  recoverable interruption/block → explicit recovery → RECOVER_MODEL
  repeated implementation recoveries → DIAGNOSTIC_PENDING → DIAGNOSTIC_REVIEW
    → product repair / host verification / architecture / human / engine repair
```

Architecture output passes deterministic checks and scope handling; it is not a
capability grant or product-owner approval. A blocker after product edits may first
enter `GIT_BLOCKED`; protected-scope review has its own preserved-checkpoint path.
`PLAN_COMPLETED` resume is inert and does not invent another ticket.

### CLI coverage

All **25** top-level parser entries are represented below; subcommands and source
lines are enumerated in the evidence manifest (71 parser nodes in total).

| Family | Commands and purpose |
|---|---|
| Setup/inspection | `init`, `status`: scaffold and read-only observation |
| Execution | `run`, `resume`, `stop`: progression, checkpoint reconciliation, cooperative stop |
| Planning | `admission` (assess/begin/status/approve/index), `cold-start` (begin/status/submit/correct/approve-requirements/approve-architecture/plan), `backlog` (begin/status/submit/approve-requirements/approve-architecture/materialize), `improvement` (request/status/submit-architecture/approve-architecture/materialize-plan/stage-successor) |
| Human gates | `gate` (release/accept-cutover/reconcile-plan/adopt-architecture) |
| Quota/evidence | `quota` (show/set/migration-dry-run/migration-apply/migration-rollback), `evidence check` |
| Repair/reconciliation | `recover-environment`, `recover-verification-failure`, `recover-generic-verification-failure`, `recover-protected-snapshot`, `reconcile-verification-evidence` |
| Compatibility/handoff | `policy-migration-dry-run`, `state-migration-dry-run`, `state-migration-apply`, `state-migration-rollback`, `engine-update` (dry-run/activate/rollback), `scope-recovery` (dry-run/apply/rollback), `plan-amendment` (dry-run/apply/rollback), `legacy-cutover` (dry-run/apply/rollback) |

### Persisted state families

These are storage contracts inferred from constructors and write sites, not a copy
of any live files. All paths below are relative to ignored `.dev-supervisor/`.

| Storage | Responsibility and relevant code |
|---|---|
| `state.json` | Current phase/ticket, completed tickets, active run, blockers/resolution, recovery context, epochs, pending commit/push, gate, counters, history/audit; `initial_state`, `load_state`, `transition`, `_finish_commit` |
| `cold-start.json`, `cold-start/` | Source specification, immutable requirements/architecture revisions, exact approvals, plan readiness; `_load_cold_start` |
| `admission.json` | Source/manifest digests, approval and provenance index; `AdmissionReview` |
| `backlog-cycle.json`, `backlog-cycles/` | Selection/revisions/approvals and materialized epoch documents; `_load_backlog_cycle` |
| `improvement.json`, `improvements/` | Explicit request, impact review, bounded plan, escalation/successor receipt; `_load_improvement` |
| `quota.json`, `quota-predecessors/` | Observation identities, consumption authorizations, invalidation, migration rollback; `ManualQuotaProvider` |
| `engine.json`, `host-owner.json`, `host-capabilities.json` | Immutable binding, writer lease, host-owned capability/push authority; constructor and binding/grant validators |
| `engine-update.json`, `engine-archives/`, `scope-recovery.json` | Qualified handoff and exact rollback evidence; engine update/scope recovery methods |
| `plan-amendment.json`, `legacy-cutover.json`, `legacy-cutover-archives/`, `state-predecessors/` | Append-only amendment/conversion receipts and predecessor recovery; amendment/state/cutover methods |
| `runs/` | Prompt, command, invocation/outcome, usage, final report, changed files/diff, deterministic logs/checks, diagnostic evidence; `CodexRunner`, `_invoke*`, `_run_verification` |
| `timing-history.json`, `stop-request.json`, lock files | Timing observations, cooperative interruption and mutual exclusion; `_record_timing`, `request_stop`, `operation_lock` |

Main runtime has 17 literal terminal states (manifest lists them); active states
include implementation, architecture, verification, scope, commit/push and diagnosis/
repair. Auxiliary state machines declare three cold-start phases, four backlog
phases and five improvement phases. Admission has scenarios A/B and compatibility
statuses, rather than the same phase vocabulary. Literal `transition` calls name
26 distinct destinations; this is a lower bound, since some phases are passed as
variables (`IMPLEMENTING`, `ARCHITECTURE_REVIEW`, quota and recovery destinations).
It is not a count of the complete state graph or reachable combinations.

### Model work versus deterministic work

Three invocation sites exist: `_invoke` for implementation/architecture,
`_invoke_diagnostic` for classification, `_invoke_supervisor_repair` for engine repair.
Every site has quota consumption before the model starts. Cold-start/admission/
backlog/improvement review prompts describe how an external assistant prepares
proposals; their submission/approval/materialization CLI paths are deterministic,
not additional automatic model invocation sites.

Report parsing, fingerprints, state validation, quota evaluation, verification commands,
Git reconciliation, status, gate operations and archive/conversion checks are
controller work. Verification commands may launch arbitrary configured programs;
calling a transition deterministic does not establish that every configured program
is pure, bounded, or free of model calls.

Human involvement is broader than genuine product ambiguity: exact requirements and
architecture approvals precede cold-start planning/backlog epochs; admission requires
exact source approval; improvements require explicit trigger/capability and impact
approval; milestone/evidence/periodic gates and engine handoffs have explicit routes.
`release_gate` requires a nonempty note, rechecks evidence/fingerprint/plan as applicable,
and requires a new human-authored commit for a product-decision gate. The code checks
HEAD changed; authorship is an operator contract, not independently authenticated.

## 4. Control and invariant evidence

Each row describes implemented checks, not an absolute guarantee outside their
preconditions. Tests listed are static coverage references from the tracked suite.

| Control / protected failure | Code / test evidence | Cost and human interaction |
|---|---|---|
| Unknown/stale quota must not authorize calls; no double consumption for one invocation | `ManualQuotaProvider.evaluate/consume/invalidate`, `_guard_quota`; quota test `test_consumption_is_idempotent_and_legacy_conversion_rolls_back` | Deterministic; medium observation one call, high TTL/count reuse; manual refresh currently required |
| Runaway model process and orphan children | `run_process_with_watchdog`, `_terminate_process_group`; main `test_watchdog_timeout_leaves_no_child_process` | Timer/process control; warning/termination; explicit recovery may consume another call |
| Stale HEAD/tree/run must not be resumed as the same checkpoint | `_model_checkpoint_matches`, `_ensure_recovery_git`; `test_stale_protected_scope_checkpoint_fails_closed_without_quota_or_model` | Deterministic hash/Git checks; operator resolves mismatches |
| Model PASS must not replace verification | `_run_verification`, `_verification_output_errors`; `test_failed_verification_prevents_commit`, `test_skipped_host_verification_fails_closed` | Configured checks and logs, no controller model call |
| Protected/later-owned scope must not silently expand | `_scope_gate`, `_preserved_paths_match`; `test_preserved_architecture_entry_blocks_modified_product_without_consuming_quota` | Deterministic first; protected review can invoke architecture; policy-specific exceptions need exact evidence |
| Commit/restart must not duplicate the product transaction | `_prepare_commit`, `_finish_commit`; `test_resume_reconciles_commit_without_duplicate_invocation_or_commit` | Git plus durable checkpoints; ambiguous history stops |
| Push target cannot be redirected by repository policy | `_verified_push_target`, `_reconcile_push`; policy `test_verified_push_target_requires_exact_branch_and_remote_urls` | Separate host grant, exact remote/branch/commit confirmation; remote check before retry |
| Model/repository cannot elevate mutation authority | `Supervisor.__init__`, `require_capability`; policy `test_capabilities_are_independent_and_intersect_host_and_repository` | Effective grants are intersection; deterministic denial |
| Audit and predecessor linkage must detect contradictory recovery evidence | `audit_event`, `_validate_state_v7`, `_append_audit_event`, `recover_generic_verification_failure`; main `test_generic_verification_recovery_audits_once_without_quota_model_or_check` | Local checksum chain; not an externally secured or signed audit log |
| Unchanged generic verification failure must not automatically rerun checks | `_generic_verification_failure_checkpoint`, `recover_generic_verification_failure`; `test_generic_verification_failure_resume_is_inert_until_explicit_recovery` | Explicit no-model reopening validates one failed configured ticket check/log; repair and full ordinary gates follow |
| Historical conversion/rollback must preserve predecessor evidence | `apply_state_migration`, `apply_legacy_cutover`; `test_qualified_cutover_is_opt_in_archives_exact_predecessor_and_rolls_back` | Dry-run, checksummed archive, explicit go; compatibility-specific limits |
| Engine handoff must exclude a stale host/writer | `_assert_engine_binding`, `_assert_writer_lease`, `activate_engine_update`; `test_immutable_binding_requires_host_local_lease_and_stale_host_cannot_write` | Identity/compatibility qualification, quiescent activation, rollback |

Limitations: watchdog evidence concerns model processes, not a universal deadline
for every verification subprocess. Unit checks do not prove distributed locking or
cross-host coordination. The inspected mechanisms deliberately remain host-local.

## 5. Historical intent versus implemented baseline

Sources: [September discussion](../dev-supervisor-discussion-2026-09-25.md),
[current backlog](../../BACKLOG.md), [2.1 candidate](../backlog/supervisor-2.1.md),
[deferred macOS qualification](../backlog/macos-platform-qualification-2.1.md).

| Material idea | Finding at inspected commit | Evidence / qualification |
|---|---|---|
| 2.0 completed/cutover; close T99 without a model or fake commit | Historical release claim; exact reconciliation mechanism implemented | `accept_legacy_cutover`, `LegacyCutoverTests`; live cutover status not inspected |
| New work belongs to a new epoch, not retroactive 2.0 changes | Implemented contract, still relevant | `_complete_plan_epoch`, `materialize_backlog_epoch`, `BacklogCycleTests` |
| Automatic short-lived Codex app-server quota reader, duration-based buckets, provider identity and manual fallback | Still relevant, automatic provider unsupported by current implementation | Constructor accepts only `manual`; `rg -n 'app-server|rateLimits' supervisor.py tests/` has no matches; manual TTL/reuse/account/model context is implemented |
| Clear current English/Russian guides and freshness-only manifest | Implemented structure, clarity is a review judgment | Guides, `check_documentation.py`, documentation tests; no semantic-equivalence proof |
| Retire old 2.0 narratives/tickets after preserving guarantees | Partially realized intent; historical material remains tracked | Governance retirement boundary versus existing `docs/architecture/` files; not evidence of completed T20 cleanup |
| Public neutralization, project-independent compatibility | Incomplete in current tracked tree; cannot claim public neutrality | Generic fixtures coexist with legacy-specific names/assumptions in historical docs/tests; no private values copied here |
| Compact fixture plus bounded self-hosted fault matrix pinned to exact T20 | Still relevant; some constituent fault tests implemented, full acceptance not established | Three fixture JSON files and fake runners; no tracked T22 acceptance artifact establishing the entire matrix/predecessor |
| One real bounded Codex acceptance receipt before release | Unverified qualification intention | Tracked sources do not establish a T24 receipt; unit tests cannot substitute for it |
| Linux baseline; macOS review/simulation only; future inbound-only Mac qualification | Current documented boundary; actual host qualification not revalidated | Operator guide and deferred candidate; do not infer real-Mac support |
| Preserve Git history and ignored recovery evidence; no forecast | Still relevant, explicit code/test support for no quota forecast | Migration archives and dashboard tests `test_dashboard_has_no_quota_forecast`, `test_timing_history_does_not_create_a_quota_forecast` |
| T20 → T21 → T22 → T23 → T24 sequence | Historical/current backlog plan, not execution evidence | Backlog names the order; tracked inventory cannot mark the sequence complete |

The September file is itself a post-2.0 update, not a verbatim earlier conversation.
Its accepted intentions do not prove current implementation or provide authorization
for new migration work.

## 6. Structural complexity and quota-relevant cost

Measured: **10,184** lines and **291** function definitions in `supervisor.py`;
**19** schemas (**533** lines), **8** prompts (**172** lines), **5** test modules
(**5,429** lines, **205** `test_` methods). Main test file: **5,026** lines.
CLI: **25** top-level entries, **71** parser nodes; state measurements as in section 3.
These are source-surface measurements, not maintainability scores or runtime costs.

Static path estimate: an ordinary successful implementation needs one model call,
then deterministic verification/scope/commit. A genuine architecture blocker adds
at least one architecture call and possibly another implementation call. Repeated
implementation recoveries can add a diagnostic call after the configured threshold
(`_maybe_trigger_diagnostic`, minimum threshold two), then repair/reclassification.
A human-evidence release can require same-ticket model review (`release_gate`).
There is no evidence here for a fixed call count for all tickets or a guaranteed
percentage saving from OpenSpec.

Duplication/cost candidates: three revision/approval/materialization flows
(cold-start, backlog, improvement), separate plan parsing/epoch/amendment machinery,
re-reading authoritative documents in model prompts, diagnostic/repair reclassification,
and periodic human checkpoints. Some overlap is intentional protection of authority
or recovery, so reducing the artifact count alone does not justify removing a gate.

An unchanged generic verification failure is explicitly inert. Interrupted verification
can resume without repeating a completed model; passed checks are retained. However,
interrupted model recovery can spend a new call on the same product tree, and the
diagnostic threshold is not by itself a global attempt/cost budget. The no-unchanged-
retry principle is stronger than what source-level bounded escalation alone proves.
Actual tokens, review frequency, wall time, unchanged retry incidence and savings are
**unavailable**, because no runtime histories were read.

## 7. OpenSpec capability evidence (installed 1.14.3)

| Capability | Reproducible source/command | Scope and comparison |
|---|---|---|
| Artifact dependency graph | `openspec schemas --json`; `openspec schema which spec-driven --json`; resolved `schema.yaml`; `status --change inventory-as-is-for-openspec-evolution --json` | Proposal precedes specs and design; tasks require specs and design; apply requires tasks. This change explicitly skips specs. Files being present is not runtime acceptance |
| Requirements/change documents | `openspec instructions proposal --change inventory-as-is-for-openspec-evolution --json`; installed schema | Proposal, capability delta requirements/scenarios, design and tasks can own planning content now represented in Supervisor documents |
| Apply context/progress | `openspec instructions apply --change inventory-as-is-for-openspec-evolution --json`; tracked apply skill | CLI returns paths/task state; assistant implements and marks checkboxes. No model scheduler, quota ledger or process watchdog demonstrated |
| Plan revision | Tracked `openspec-update-change/SKILL.md` | Revises planning artifacts coherently without editing code; does not provide Supervisor's exact-digest operator authorization |
| Validation | `openspec validate --help`; strict validation of this change | Artifact/spec checks, not execution of product tests or proof of acceptance; valid changes may have unfinished tasks |
| Sync | Tracked `openspec-sync-specs/SKILL.md` | Assistant merges ADDED/MODIFIED/REMOVED/RENAMED requirement deltas into main specs; does not commit a verified product transaction |
| Archive | `openspec archive --help`; tracked archive skill | CLI archive can update specs; skill can sync first and move change. `--skip-specs`/metadata handle documentation changes. Does not replace runtime predecessor archives |
| Stores and root selection | `openspec store --help`, `list --json`; generated skill store-selection rules | Registered standalone spec repositories selected with `--store`; unused here. Not writer leases, distributed execution or remote product persistence |

Installed workflow files: [apply](../../.agents/skills/openspec-apply-change/SKILL.md),
[update](../../.agents/skills/openspec-update-change/SKILL.md),
[sync](../../.agents/skills/openspec-sync-specs/SKILL.md),
[archive](../../.agents/skills/openspec-archive-change/SKILL.md),
[propose](../../.agents/skills/openspec-propose/SKILL.md),
[explore](../../.agents/skills/openspec-explore/SKILL.md).

Absence conclusions are bounded to these inspected interfaces and workflows; they
are not claims that no external OpenSpec integration could supply runtime services.

## 8. Ownership and overlap matrix

Current owners are Supervisor (S), OpenSpec (O), operator (H). Proposed owners are
recommendations only. Confidence H/M means strong direct evidence / design inference
requiring an integration experiment. Dependencies describe conditions, not an ordered
migration plan.

| Unit / responsibility | Current → proposed owner; classification | Evidence | Safety consequence / dependency | Confidence |
|---|---|---|---|---|
| C1 launcher/init | S → S; retain | `initialize_repository`, `dev` | Keep immutable binding; planning scaffold must respect selected planning owner | H |
| C2 configuration/grants | S/H → S/H; retain | policy validation and tests | OpenSpec content cannot grant push/mutation/quota authority | H |
| C3 source requirements, design, tickets | S → O; delegate to OpenSpec | cold-start/backlog methods versus proposal/spec/design/tasks | Stop parallel content authority only after task/change identity and content binding exist | M |
| C3 admission mapping | S/H → O content + S input validation; integrate | `AdmissionReview`, apply context | Preserve provenance/digest checks without a second project-specific planning format | M |
| C3 exact approvals and revisions | S/H → H authority + S digest record over O content; simplify | approve/materialize methods | Artifact readiness cannot be treated as human authorization; invalidate on relevant content change | M |
| C3 epochs/amendments | S → O task content + S execution cursor; simplify | `_new_plan_epoch`, amendment methods | Preserve completed history and in-flight identity; task renumbering cannot silently move cursor | M |
| C3 improvement/self-development | S/H → O change content + S/H capability/activation; integrate | improvement methods/tests | User trigger and isolated successor requirement survive | M |
| C4 execution/state/locks | S → S; retain | `_run_loop`, `resume`, `operation_lock` | A checked task is not a resumable invocation/commit checkpoint | H |
| C4 dashboard/timing | S → S execution view + O task progress; simplify | `status`, `dashboard`, `_record_timing` | Avoid divergent progress; preserve truthful recovery action | M |
| C5 quota | S/H → S/H; retain | provider/consume tests | No authorization from artifact existence or assistant prose | H |
| C6 processes/reports/diagnostic repair | S → S; retain | runner, validators, `_invoke*` | Preserve bounded execution and read-only classification; broader repair strategy unresolved | H |
| C7 verification/scope/Git/recovery | S/H → S/H; retain | control matrix | Sync/archive cannot substitute for full checks or exact transaction recovery | H |
| C8 live identity/handoff | S/H → S/H; retain | binding/lease/update tests | OpenSpec store registration is not engine qualification | H |
| C8 historical compatibility routes | S → unresolved; unresolved | cutover/state/scope recovery methods | Need supported-version/retention evidence before selecting retirement; no removal authorized | M |
| C9 planning schemas | S → O artifact format + S boundary validators; integrate | approval/admission/cold-start/backlog/improvement/epoch schema group | Avoid keeping duplicate payload formats; preserve authorization/input validation | M |
| C9 runtime schemas | S → S; retain | reports, policy, audit, grants/owner, engine, state schema group | Preserve versions and semantic validation beyond JSON shape | H |
| C10 planning prompts | S → O workflows; delegate to OpenSpec | cold-start/admission/backlog/improvement prompts | Stop separate proposal generation only when provenance and bounded scope remain checked | M |
| C10 execution prompts | S → S consuming O context; integrate | implement/architecture/diagnose/repair prompts | Replace hardcoded ticket paths with validated context; retain role restrictions | M |
| C11 runtime tests/fixtures | S → S; retain | five modules and fixtures | Needed regardless of planning owner; missing acceptance evidence stays explicit | H |
| C11 documentation checks | S → S; retain | checker/manifest/tests | One maintained operator translation pair; dated inventory translation is separate | H |
| C12 current operator/backlog material | S/H → S/H operations + O future change content; integrate | guide/governance/backlog | Backlog candidates remain nonexecutable until selected; operational authority remains explicit | M |
| C12 completed historical planning documents | S → Git historical evidence; retire (candidate) | historical status headers/governance | Requires retention/coverage decisions later; no deletion in this assessment | M |
| C12 OpenSpec config/workflows | O → O; retain | selected root/schema/generated skills | One selected planning root, version-pinned interpretation | H |

## 9. Duplicate truths and handoff failure modes

These are prospective integration requirements; no adapter implementing them exists.

| Proposed delegation | What would cease being planning authority | Drift detection required before execution |
|---|---|---|
| Requirements/design to O | Supervisor-generated requirements/architecture payload copies and their separate editable originals | Record root/change identity plus digests of relevant O inputs; changed digest invalidates affected approval; reject mismatched copies |
| Task decomposition to O | Separate editable ticket hierarchy/plan order and new parallel materializations | Bind execution to stable task identity and content digest; detect rename, deletion, reorder or dependency change; stop in-flight work if binding differs |
| Planning prompt generation to O | Separate cold-start/backlog/improvement proposal templates as competing contracts | Confirm returned context root/paths/schema and input digests; reject unsupported formats rather than infer a mapping |
| Change archival to O | Supervisor's archive of planning content as a second canonical spec history | Keep references to archived change/commit/digests in execution records; check archive/sync result independently of runtime completion |

OpenSpec checkbox completion, Supervisor ticket completion, successful commit and
remote persistence are four different facts. An integration must reconcile them
against durable acceptance evidence, not propagate one boolean in both directions.
Approvals must bind the reviewed content; OpenSpec edits can otherwise leave a stale
Supervisor approval valid. Store/root selection must be recorded to avoid resolving
an identical change name in another repository. Runtime archives continue to own
rollback and must not be removed when a planning change is archived.

## 10. Candidate operating model before any migration plan

This section is a recommendation, not current behavior. Each responsibility has
one proposed authority: O for source requirements, spec deltas, design, task content
and planning archive; S for execution cursor, process/verification/checkpoint/Git
state, quota consumption and recovery audit; H for product intent, material tradeoffs,
capability grants and irreversible-operation authorization. Policy is a restriction
on host authority. Crossings carry selected root/change/task identity, content digests,
acceptance references and explicit authorization provenance. S references O content
rather than maintaining another editable plan; O progress is reconciled only from
S's accepted execution result. Existing S controls remain in force until replaced
through separate authorized implementation.

### Assurance modes

All three candidate modes keep single-writer ownership, explicit authority,
checkpoint identity, recorded quota consumption, no duplicate side effects, safe
Git transactions, secret handling and mandatory acceptance checks. None permits a
generic force-state, unchanged automatic failure retry or implicitly authorized
irreversible operation.

| Candidate mode | Additional checks and review | Trigger/evidence |
|---|---|---|
| Exploration | Read-only discovery by default; local disposable experiments only within authorized scope; record unresolved intent, no completion claim | Reversible isolated investigation; no persistent/public/trust-boundary change |
| Ordinary startup delivery | Focused checks plus required regression; architecture review only for material boundary changes; user gate only for material intent/authority decisions | Approved bounded requirements; tests/diff and content binding support autonomous local choices |
| Protected/release | Broader regression, compatibility/rollback evidence and explicit release/operator decision | Persistent data, public contracts, sensitive trust boundary, broad operational impact or protected/release policy |

Historical compatibility checks apply when a supported legacy version or live
recovery record requires them, not merely because an old ticket exists. Whether a
route is dispensable is unresolved here; retirement criteria/schedule belong to the
excluded roadmap work.

### Decision routing

Evaluate ambiguity first, then authority/irreversibility, blast radius, public/data/
trust boundary, operational cost, reversibility and tradeoff materiality. Where routes
overlap, the user decision route wins; an architecture pass may prepare alternatives
but cannot grant permission.

| Example / condition | Route | Evidence needed |
|---|---|---|
| Rename internal helper or use an existing local abstraction within approved requirements | Autonomous implementation | Local reversible diff and relevant checks; no new public/data/trust/cost commitment |
| Add dependency, alter component boundary or public contract, change persistent representation, materially increase service cost | Architecture review | Alternatives, simpler option, compatibility/risk/cost analysis; user decision if materially different commitments remain |
| Requirement ambiguity changes product outcome; destructive data/history operation; credentials/grants; external commitment; material tradeoff or risk tolerance | User decision | Concrete alternatives and consequences; explicit scope/authority; no implementation inferred from silence |
| Known configured verification failure with unchanged checkpoint | Deterministic stop/recovery validation | Existing exact evidence; model repair only when authorized with a changed repair hypothesis |
| Legacy migration or engine activation | Architecture/qualification plus operator go | Exact predecessor/compatibility/rollback identity and quiescence; never ordinary local-refactor discretion |

### Quota economy without forecasting

Use deterministic preflight before consuming quota; reuse already selected OpenSpec
context and unchanged evidence; skip model reviews for mechanically decidable
transitions. A changed task digest, checkpoint, failed-check signature or explicit
repair hypothesis must justify a new attempt. Bound attempts/calls/time by work item
and role; stop and escalate when a budget is exhausted. Budgets need separate policy
design and are not claimed to exist globally today.

Collect counts of authorized/started/completed calls by role and task, repeated calls
at the same content/checkpoint/failure signature, diagnostic/review calls, deterministic
handoffs, stops, elapsed time and recorded token usage where available. Use controller
events and existing outputs, with redacted identities/aggregates; no model calls for
bookkeeping, no secrets or prompt text in metrics. Compare calls per accepted task
and repeat-call rate across comparable scopes, separating model and verification
time. TTL observations describe current permission; they predict neither remaining
tickets nor future availability. Numerical savings require runtime evidence and a
comparable baseline; this inventory supplies neither.

## 11. Validation and remaining uncertainty

The companion JSON is a static evidence index, not a new runtime contract. English
and Russian reports use the same section numbers, component IDs, measurements and
classification rows. They are dated assessment snapshots outside the sole maintained
operator-guide translation pair; the translation manifest is unchanged.

Checks for this delivery: documentation governance, local Markdown links in both
reports, referenced code/test symbol existence, evidence source hashes, whitespace,
strict OpenSpec validation and the existing offline unit suite. On 2026-11-18 these checks passed; the existing suite ran **205 tests** in
64.331 seconds with result `OK`. A passing unit suite is not a real Codex acceptance
receipt. Complete-change validation (task 6.1) is not asserted while
the requested migration-roadmap work remains intentionally unperformed.

Remaining evidence gaps: actual quota/run economics; completion of T21–T24 and real
acceptance; legacy recovery retention needs; stable task identity under OpenSpec edits;
CLI subprocess versus another integration interface; the scope of future assurance
profiles. These gaps limit future design decisions, not the source facts above.
