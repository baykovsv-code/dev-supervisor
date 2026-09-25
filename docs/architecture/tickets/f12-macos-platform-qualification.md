# F12: macOS platform contract and qualification

## Objective

Make macOS a verified Supervisor 2.0 host platform without guessing a particular Mac
model or freezing the contract to software versions that have not yet been tested.

## Prerequisites

- T00-T11 and all earlier inserted prerequisites are complete.
- A contemporary Apple Silicon Mac with an Apple-supported macOS release is available
  for qualification.
- Maintained compatible Python 3, Git, and the Codex CLI version required by the
  current normative documentation are installed.

## Scope

- Define Linux as the existing baseline and contemporary Apple Silicon macOS as the
  initial additional supported host class. Treat Intel Macs, obsolete macOS releases,
  and untested tool versions as best-effort rather than implicitly supported.
- Capture a redacted qualification manifest containing the exact Mac hardware
  identifier, CPU architecture, macOS version/build, filesystem type and
  case-sensitivity, Python version, Git version, Codex CLI version, and candidate
  Supervisor revision. Do not collect host names, account identifiers, credentials,
  tokens, home-directory paths, or other unnecessary machine identity.
- Audit and exercise every host-sensitive boundary: `fcntl.flock`, atomic temporary
  writes plus `fsync`/`os.replace`, executable permissions, symlinks and resolved
  paths, case-insensitive filesystem collisions, temporary directories, subprocess
  sessions, signal/process-group termination, Git command behavior, and launcher
  engine binding.
- Add deterministic macOS coverage for initialization, read-only status, concurrent
  lock exclusion, stop/watchdog cleanup, verification, local commit, disabled-push
  behavior, local-remote push confirmation/recovery, immutable engine update and
  rollback, and the supported T11 migration dry-run/rejection paths.
- Run the complete discovered test suite, Python compilation, and T00 compatibility
  harness on both the Linux baseline and the qualifying macOS host.
- Perform one isolated end-to-end macOS rehearsal through the ordinary Supervisor
  workflow, including the installed Codex CLI. Any live model invocation requires the
  normal explicit quota authorization and remains confined to a disposable fixture.
- Make only bounded portability changes. Any missing primitive or semantic mismatch
  that cannot preserve the existing guard must fail closed and be documented as an
  unsupported environment.
- Publish a repeatable macOS qualification procedure and evidence template. Record
  exact tested versions on each run so the support statement can roll forward without
  inventing an untested minimum version.

- Files/modules: `supervisor.py`, launchers, `tests/`, platform test configuration,
  and `docs/` as required by discovered portability gaps.

## Acceptance criteria

- The full Linux regression suite remains green, and the same discovered suite and
  T00 compatibility harness pass on the qualifying Apple Silicon macOS host.
- Recorded evidence identifies the exact qualified environment and candidate revision
  while containing no credentials or unnecessary host/user identity.
- The isolated macOS rehearsal proves `init`, `status`, locking, process cleanup,
  deterministic verification, local commit, push denial and local-remote recovery,
  engine update/rollback, and supported migration behavior without manual state edits.
- One ordinary isolated workflow reaches its expected terminal result using the
  installed Codex CLI; it neither touches the live `personal-assistant` repository nor
  reuses quota authorization.
- Locking, atomic-write, process termination, Git lineage, capability, audit,
  compatibility, and single-controller guarantees have identical safety outcomes on
  Linux and macOS. Unsupported conditions stop explicitly instead of degrading a
  guard.
- Normative operator documentation states the rolling support contract, qualification
  procedure, exact-evidence requirement, and exclusions for Intel, obsolete, and
  otherwise unqualified environments.
- T12 consumes and links the F12 evidence before final cutover readiness can be
  reported.

## Documentation impact

`Required — platform support contract and operator qualification workflow.` Update the
normative English prerequisites, platform limitations, qualification/requalification,
and recovery guidance plus every affected document in the maintained Russian operator
subset.

## Non-goals

- guaranteeing every Mac model, Intel Mac, obsolete macOS release, package-manager
  layout, shell customization, or untested Python/Git/Codex CLI version;
- adding Windows support;
- replacing host qualification with mocks or Linux-only CI;
- weakening a safety guard to obtain cross-platform behavior;
- performing the live `personal-assistant` cutover.
