# T09: Authorized push and remote persistence

## Objective

Implement the existing GitHub persistence backlog requirement without weakening the
default-off capability boundary.

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
- Failure preserves the local commit and never reports remote completion.
- Resume after an interrupted successful push creates neither a duplicate commit nor a
  second required push.
- Tests cover all backlog failure and confirmation cases with isolated remotes.
- The T00 personal-assistant compatibility harness proves that an absent push
  capability adds no remote command, state mutation, or new prerequisite to the
  existing T30 human gate.

## Non-goals

- credential provisioning;
- distributed locking through GitHub.
