# Supervisor 2.1 candidate: restricted-workplace macOS qualification

Status: **backlog input only — not an executable 2.0 ticket or cutover prerequisite**.

## Objective

Prepare and qualify a Supervisor 2.1 successor for a contemporary workplace Mac after
the Linux-hosted Supervisor 2.0 generation has completed cutover and controls its own
successor-development workflow.

## Host constraint

- Reviewed code and a self-contained test bundle may be transferred onto the Mac.
- Source code, raw logs, generated artifacts, paths, machine identifiers, account
  information, and credentials may not be transferred back from the Mac.
- The operator may communicate an oral overall result, stable test-stage identifiers,
  and a human description of a problem. Those descriptions are observations, not raw
  machine evidence.
- No workflow may require weakening the workplace host's information-flow policy.

## Required design

- Produce an inbound-only, self-contained local qualification command with stable,
  documented stage identifiers for locking, atomic writes, permissions, symlinks and
  path resolution, case-sensitive/case-insensitive behavior, temporary files,
  subprocess sessions and termination, Git operations, launcher binding, engine
  update/rollback, and supported migration paths.
- Keep detailed diagnostics and environment data local to the Mac. Present a concise
  local PASS/FAIL checklist so the operator can report a failing stage and describe
  symptoms orally without exporting the underlying log.
- Support an iterative loop in which fixes are developed and reviewed in the normal
  repository, transferred inward, and locally rerun. Never depend on copying modified
  code or diagnostic artifacts back from the workplace Mac.
- Record only a human-authored attestation in the normal repository: candidate
  revision, the non-sensitive environment description the operator is allowed to
  provide, stages reported PASS/FAIL, date, limitations, and the operator's decision.
  Do not reconstruct or invent unavailable machine evidence.
- Distinguish `operator-qualified` from independently reproducible qualification.
  Missing raw evidence lowers assurance and must remain visible in documentation; it
  is never represented as a machine-verified result.
- Keep Linux as the established 2.0 baseline. Do not make macOS a supported 2.1 host
  until the local checklist and explicit human gate pass for the candidate revision.

## Candidate acceptance criteria

- Supervisor 2.0 creates and approves a bounded 2.1 plan before implementation.
- The inbound bundle contains all required code, fixtures, instructions, and checks;
  qualification needs no outbound code, log, artifact, or network transfer.
- Local checks cover `init`, read-only `status`, lock exclusion, stop/watchdog cleanup,
  deterministic verification, local commit, disabled-push behavior, local-only remote
  recovery where workplace policy permits it, engine update/rollback, and supported
  migration behavior.
- One isolated ordinary workflow using the locally installed Codex CLI reaches its
  expected terminal result without touching live `personal-assistant` state. Any model
  call uses normal explicit quota authorization.
- A failed stage remains unsupported until a corrected inbound candidate passes; an
  oral problem description may guide diagnosis but cannot waive or override the stage.
- The repository records the exact limits of human-attested evidence and makes no
  claim for Intel Macs, obsolete macOS releases, other untested hardware/software, or
  machines outside the attested environment class.

## Documentation impact

`Required — 2.1 platform support and restricted-host qualification workflow.` Update
normative English and affected maintained Russian operator documentation when this
candidate becomes an approved 2.1 ticket.

## Non-goals

- delaying the initial Linux-hosted Supervisor 2.0 cutover;
- exporting workplace code, logs, diagnostics, or machine identity;
- treating oral reports as raw or independently reproducible evidence;
- weakening a safety guard to obtain a macOS PASS;
- adding Windows support.
