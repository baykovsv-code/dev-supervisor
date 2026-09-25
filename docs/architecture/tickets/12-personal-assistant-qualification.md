# T12: Personal-assistant qualification and operator runbook

## Objective

Qualify 2.0 on an isolated copy of real `personal-assistant` state and prepare the
final human cutover decision.

## Scope

- Prerequisites: completed T00-T11, including F09, F10, and F11, in authoritative
  plan order.

- Capture redacted, checksummed fixtures for every intended source state, including
  the T30 human evidence gate.
- Rehearse dry-run, cutover, read-only status/reconciliation, first controlled ticket,
  stop, rollback, and re-entry on an isolated repository copy.
- Prove no product diff, no duplicate invocation/commit, no quota reuse, and no dual
  controller interval.
- Produce an English operator runbook with preflight, commands, expected evidence,
  abort conditions, and recovery.

- Files/modules: `tests/`, `docs/`.

## Acceptance criteria

- All supported fixtures and fault injections pass.
- Compatibility evidence from every implementation-ticket commit through T11 in
  authoritative plan order, including F09, is present and linked; T12 is the final
  integration rehearsal, not the first personal-assistant compatibility check.
- A second operator can follow the runbook without undocumented state edits.
- Live product HEAD/fingerprint and T30 evidence remain untouched by rehearsal.
- Results are ready for the configured post-T12 human gate.
- The final pre-cutover documentation review passes: the maintained-subset manifest,
  pair/link/staleness checks, current English and Russian operator workflows, legacy
  classifications, and retained migration/rollback/compatibility/cutover evidence are
  complete and linked. This check does not assert semantic translation equivalence.

## Documentation impact

`Required — operator runbook and qualification evidence.` Update the normative English
qualification/cutover runbook and every affected maintained Russian operator document;
record manifest freshness and evidence links for the final gate.

## Non-goals

- performing live cutover;
- releasing the T30 product evidence gate on behalf of the owner.
