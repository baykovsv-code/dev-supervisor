# Development Supervisor 2.0 Backlog

This backlog records requirements that must be resolved during the architecture phase.
It does not prescribe the implementation design or authorize implementation work.

The consolidated English requirement index is
[docs/architecture/requirements-index.md](docs/architecture/requirements-index.md).
Its source lineage includes the Russian backlog and AS-IS assessment prepared in the
legacy repository at commit `854083f51c9aedf33ec2d9654fc67aacff84af8a`.

## Safety clarification

Self-modification, user-requested out-of-plan modification, and `git push` are
independent capabilities. All are disabled by default and fail closed when their
configuration is absent or invalid. Repository-controlled content may restrict a
capability but cannot enable it; enabling authority is host/operator controlled.

The persistence requirement below applies only after the push capability has been
explicitly enabled. While it is disabled, a verified local commit is reported as
`locally committed`, never as remotely persisted. This distinction resolves the
otherwise unsafe interpretation that merely cloning this backlog could authorize a
push.

## Persist accepted changes to GitHub

Development Supervisor must commit accepted project changes to Git and push them to
the configured canonical GitHub repository. A change is not considered durably
completed merely because a local commit exists.

Required behavior:

- the canonical remote and target branch are explicit, validated configuration;
- every push targets the exact commit produced by the verified change workflow;
- completion is reported only after the remote branch is confirmed to contain that
  commit;
- authentication, authorization, network, non-fast-forward, and branch-protection
  failures stop the workflow with an actionable status and preserve the local commit;
- retry is idempotent and must not create a duplicate commit;
- force-push and history rewriting are forbidden unless a separate, explicitly
  approved recovery procedure requires them;
- credentials and tokens are never written to project state, logs, prompts, or run
  artifacts;
- audit history records the local commit, remote, branch, push attempt, and confirmed
  remote commit;
- an offline mode, if supported, must distinguish `locally committed` from
  `completed and pushed` and require later reconciliation.

Acceptance criteria:

- a successful workflow leaves the verified commit reachable from the configured
  GitHub branch;
- a failed push never reports the change as fully completed and does not discard the
  local commit;
- resuming after a successful but interrupted push recognizes the remote commit
  without pushing or committing it again;
- tests cover unavailable credentials, unavailable network, rejected updates,
  protected branches, interrupted confirmation, and successful retry.
