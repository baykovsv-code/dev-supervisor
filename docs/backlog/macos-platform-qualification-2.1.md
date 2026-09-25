# Deferred candidate: real-device macOS qualification

Status: **deferred beyond 2.1 — not part of the approved 2.1 real-device test scope**.

## Objective

Eventually qualify a future Supervisor successor on a real contemporary Mac. During
2.1, only deterministic portability review and simulated platform-contract tests are
in scope. They do not constitute real-device qualification and do not authorize a
macOS support claim.

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

- A future plan explicitly opts into real-device Mac qualification; the 2.1 plan does
  not.
- The inbound bundle contains all required code, fixtures, instructions, and checks;
  qualification needs no outbound code, log, artifact, or network transfer.
- Local checks cover `init`, read-only `status`, lock exclusion, stop/watchdog cleanup,
  deterministic verification, local commit, disabled-push behavior, local-only remote
  recovery where workplace policy permits it, engine update/rollback, and supported
  migration behavior.
- One isolated ordinary workflow using the locally installed Codex CLI reaches its
  expected terminal result without touching live managed-project state. Any model call
  uses normal explicit quota authorization.
- A failed stage remains unsupported until a corrected inbound candidate passes; an
  oral problem description may guide diagnosis but cannot waive or override the stage.
- The repository records the exact limits of human-attested evidence and makes no
  claim for Intel Macs, obsolete macOS releases, other untested hardware/software, or
  machines outside the attested environment class.

## Documentation impact

`Required when activated in a future release — platform support and restricted-host
qualification workflow.` For 2.1, documentation must state that real-device Mac
qualification was not performed and macOS remains unsupported.

## Non-goals

- treating 2.1 simulated portability tests as a real Mac PASS;
- exporting workplace code, logs, diagnostics, or machine identity;
- treating oral reports as raw or independently reproducible evidence;
- weakening a safety guard to obtain a macOS PASS;
- adding Windows support.
