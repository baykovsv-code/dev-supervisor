# T09: Authorized push and remote persistence

## Objective

Implement the existing GitHub persistence backlog requirement without weakening the
default-off capability boundary.

## Preconditions

- F09 is complete; generic deterministic-verification failures have an explicit
  fail-closed same-ticket recovery path and cannot loop unchanged.

## Approved configuration contract

- Host/operator configuration is authoritative for the canonical Git remote name,
  expected credential-free URL identity, and exact target branch.
- `repository_push` remains an independent boolean capability and defaults to
  disabled. Repository content cannot supply or redirect the authoritative target.
- Repository `expected_branch` is an additional restriction: it, the checked-out
  branch, and the host target branch must match exactly before a remote command runs.
- The configured Git remote URL must match the host-owned identity. Supervisor does
  not infer a target from `origin` or any other Git default.
- Missing, malformed, credential-bearing, or mismatched target configuration fails
  closed. Credentials remain external in an SSH agent or Git credential helper.
- Existing and legacy configurations migrate with no target and remain unable to
  push. An operator must explicitly configure a valid host target before enabling
  push. State and audit persist only safe target identity, never credentials.

## Scope

- Add explicit canonical remote/branch validation and a post-local-commit push state.
- Attempt no remote command while `repository_push` is disabled; report
  `LOCALLY_COMMITTED` truthfully.
- When enabled, push only the exact verified commit and confirm remote reachability
  before `REMOTELY_PERSISTED`.
- Reconcile authentication, network, non-fast-forward, protection, interruption, and
  already-successful push outcomes idempotently.
- Keep credentials out of state, prompts, logs, and artifacts; record safe audit data.
- Forbid force-push/history rewrite in normal operation.

- Files/modules: `supervisor.py`, `schemas/`, `tests/`.

## Acceptance criteria

- Default configuration executes no push subprocess.
- Repository changes cannot redirect an enabled push, and an enabled capability with
  an absent or mismatched host target executes no remote subprocess.
- Migration never infers a target from an existing Git remote and preserves disabled,
  fail-closed behavior until explicit host configuration is valid.
- Target validation rejects embedded credentials and any mismatch between the current
  branch, repository `expected_branch`, host target branch, or configured remote URL.
- Failure preserves the local commit and never reports remote completion.
- Resume after an interrupted successful push creates neither a duplicate commit nor a
  second required push.
- Tests cover all backlog failure and confirmation cases with isolated remotes.
- The T00 personal-assistant compatibility harness proves that an absent push
  capability adds no remote command, state mutation, or new prerequisite to the
  existing T30 human gate.

## Non-goals

- credential provisioning;
- repository-owned or automatically discovered push destinations;
- distributed locking through GitHub.
