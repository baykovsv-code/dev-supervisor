# T12: Personal-assistant qualification and operator runbook

## Objective

Qualify 2.0 on an isolated copy of real `personal-assistant` state and prepare the
final human cutover decision.

## Prerequisites

- T00-T11 and every inserted prerequisite, including F09, F10, F11, and F12, are
  complete in authoritative plan order.
- The macOS platform qualification evidence from F12 is current and linked.

## Scope

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
- Compatibility evidence from every implementation-ticket commit through F12 in
  authoritative plan order, including inserted prerequisites, is present and linked;
  T12 is the final
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
qualification/cutover runbook and every affected maintained Russian operator document.
Include the qualified macOS environment, support boundary, preflight, abort conditions,
F12 evidence links, translation-manifest freshness, and final-gate evidence links.

## Non-goals

- performing live cutover;
- releasing the T30 product evidence gate on behalf of the owner.
