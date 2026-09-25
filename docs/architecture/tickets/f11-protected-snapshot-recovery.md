# F11: Protected supervisor-control-path snapshot recovery

## Objective

Port the exact protected supervisor-control-path snapshot recovery defect fix
demonstrated by legacy controller commit `6b86e7b`, without creating a general override
mechanism or expanding into T11 cutover work.

## Prerequisites

- T00-T10, F09, and F10 are complete.
- The durable checkpoint represents a completed, read-only protected-scope
  architecture review blocked only by the legacy product-snapshot count mismatch.

## Scope

- Exclude configured supervisor-control paths from product-snapshot comparison while
  continuing to validate those paths through the full Git checkpoint fingerprint.
- Add one explicit, audited reprocessing path for the qualifying false block. It must
  validate the exact ticket, run, HEAD, branch, dirty path set and contents, structured
  report, artifacts, quota audit, and complete checkpoint fingerprint.
- Reprocess the preserved completed review without another model invocation or quota
  authorization only after every identity and content check succeeds.
- Fail closed without changing the preserved checkpoint when any evidence is missing,
  ambiguous, stale, or altered.
- Add focused positive and stale-checkpoint regression tests and keep the T00
  compatibility harness passing.

- Files/modules: `supervisor.py`, `schemas/`, `tests/`.

## Acceptance criteria

- Product-snapshot comparison ignores only configured supervisor-control paths; a
  full Git checkpoint fingerprint change in any such path still blocks recovery.
- An exact eligible false-block checkpoint is reprocessed with no new model call and
  no quota consumption, preserving its original report and artifacts.
- Changed ticket/run identity, HEAD, branch, dirty paths or bytes, report, artifacts,
  quota audit, or fingerprint each fail closed in focused regression tests.
- Ineligible protected-scope states, ordinary architecture failures, and ambiguous
  checkpoints cannot enter this recovery path.
- The ordinary scope, commit, compatibility, and audit gates remain in force.

## Documentation impact

`Required — recovery workflow.` Update normative English recovery instructions and
every affected maintained Russian operator document with eligibility, the explicit
action, exact-evidence checks, no-model/no-quota behavior, and fail-closed outcomes.

## Non-goals

- a general force-state, break-glass, checkpoint-editing, or evidence-waiver framework;
- weakening full Git fingerprint validation for supervisor-control paths;
- rerunning a model or consuming another quota authorization for an exact checkpoint;
- implementing or broadening the T11 cutover.
