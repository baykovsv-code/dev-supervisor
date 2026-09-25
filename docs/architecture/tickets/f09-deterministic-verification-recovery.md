# F09: Generic deterministic-verification failure recovery

## Objective

Prevent an unchanged generic `VERIFICATION_FAILED` checkpoint from repeatedly running
the same failed check, while preserving bounded same-ticket repair and every existing
completion gate.

## Preconditions

- T00–T08 are complete.
- The current failure is not a mandatory host-verification failure, which remains on
  its stricter existing reconciliation path.

## Scope

- Replace automatic unchanged retry of a generic `VERIFICATION_FAILED` checkpoint with
  an explicit operator recovery action that fails closed unless all recovery evidence
  is exact.
- Validate the current ticket and run, starting HEAD, post-model fingerprint and
  changed-file checkpoint, exactly one failed deterministic check that still matches
  the ticket's current configured check identity and command, and that check's durable
  run log.
- Reject stale or changed checkpoints, absent or ambiguous failures, missing or unsafe
  logs, configuration drift, and any failure classified for mandatory host
  verification without changing the preserved checkpoint.
- Record an audit event binding the recovery action to the ticket, run, HEAD,
  fingerprint, failed check, and log before entering bounded same-ticket repair.
- Make the recovery action itself consume no quota and invoke no model. A later
  explicit resume uses the ordinary quota guard before any repair model invocation.
- After repair, discard no required verification coverage: run the full configured
  verification suite, then the ordinary scope and commit gates.
- Preserve interrupted-recovery idempotence and the T00 legacy-reference
  compatibility boundary.

- Files/modules: `supervisor.py`, `schemas/`, `tests/`.

## Acceptance criteria

- Ordinary resume from an unchanged generic `VERIFICATION_FAILED` checkpoint does not
  rerun the failed check and reports the required explicit recovery action.
- The explicit action reaches bounded same-ticket repair only for one exact configured
  failed check with an available safe log and an unchanged model checkpoint.
- The action produces one durable audit record and starts neither a model nor a check;
  it consumes no quota authorization.
- Multiple or unconfigured failures, evidence/configuration drift, malformed or
  missing logs, and changed HEAD, fingerprint, or changed-file identity fail closed.
- Mandatory host-verification failures cannot enter this generic path and retain their
  stricter reconciliation and evidence rules.
- Repair requires a separately quota-authorized model invocation, then reruns the full
  verification suite and passes normal scope and commit validation; the failed check
  alone cannot complete the ticket.
- Crash and repeated-action tests prove the transition and audit are idempotent and do
  not create duplicate repair invocations or commits.
- The T00 legacy-reference compatibility harness passes without state mutation, a
  model invocation, or a new prerequisite at its existing T30 human gate.

## Non-goals

- weakening or replacing mandatory host-verification handling;
- bypassing, waiving, or marking a failed check as passed;
- repairing product code during the recovery action;
- enabling any mutation or push capability.
