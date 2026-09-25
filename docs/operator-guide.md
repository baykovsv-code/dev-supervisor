# Development Supervisor operator guide

This is the normative English guide for an operator. It explains normal operation
without requiring architecture documents. The reviewed Russian counterpart is
[operator-guide.ru.md](operator-guide.ru.md). English controls if the two texts differ.
The translation check is a freshness alarm, not a claim of semantic equivalence; see
[documentation governance](documentation-governance.md).

## Install and orient yourself

You need Python 3 and Git. A model invocation also needs the configured Codex CLI and
an explicit quota authorization. Linux is qualified. No real Mac was tested for this
release, so macOS is unsupported.

From the engine checkout, initialize a repository:

```bash
./supervisor init /path/to/project
cd /path/to/project
./dev status
```

To use a reviewed existing policy, run `./supervisor init /path/to/project --policy
/path/to/policy.json`. Initialization creates an executable `dev` launcher, a tracked
`dev-supervisor.json` policy, an ignored `.dev-supervisor/` runtime directory, and—only
for the default setup—the minimum plan and ticket scaffold. It refuses to overwrite
conflicting control files. Review and commit generated tracked files before running.

If the engine checkout moves, set `DEV_SUPERVISOR_HOME` to its new location for the
local launcher binding. Do not edit ignored runtime files to repair a binding.

## Mental model

There are four boundaries:

1. The engine checkout contains the controller, prompts, schemas, tests, and guides.
2. The controlled repository contains product files, policy, plans, tickets, and the
   launcher.
3. The ignored `.dev-supervisor/` directory contains local state, locks, quota
   observations, and run evidence.
4. A configured remote is only a persistence target; it is not a lock or authority.

One managed repository has one writer and one active immutable engine generation.
`status` is read-only. Treat an unexpected branch, HEAD, ticket, engine identity,
working-tree fingerprint, policy version, or gate as a stop condition.

The normal lifecycle moves from review and approved planning to `READY`, ticket work,
verification, a local commit, and a bounded stop. Completing a plan does not select or
start more work. Unknown state, quota, ownership, platform, compatibility, or protocol
never grants permission.

## Ordinary operation

Before a model call, inspect the state and supply a current, trusted observation:

```bash
./dev status
./dev quota set --five-hour <percent> --weekly <percent>
./dev run
```

Use `./dev resume` only after reading the status and any displayed gate or recovery
instruction. A quota observation authorizes only the bounded invocation allowed by
policy; it does not approve architecture, release a human gate, enable a capability,
or authorize a push. Never guess percentages or reset times. If an automatic
observation is unavailable or ambiguous, it is not permission: use the explicit manual
command above with a current trusted value, or stop.

After a run, inspect:

```bash
./dev status
git status --short --branch
git log --oneline --decorate -5
```

The Supervisor normally creates the verified implementation commit. Do not pre-commit,
amend, rebase, squash, reset, clean, or stash a recorded checkpoint. Stage exact paths
only for a documented, quiescent human-authored action.

## Gates and safe stops

`HUMAN_GATE` and `PERIODIC_CHECKPOINT` are successful bounded stops. They do not mean
that `resume` is allowed. If status displays `resume_command: null`, ordinary resume
must leave the gate closed. Inspect the required evidence, plan, tree, completed
tickets, and test results; release only with the documented gate command and a
meaningful note.

Stop safely at any time:

```bash
./dev stop
./dev status
```

Do not power off while a model, verification, scope, or commit operation is active.
When status reports a quiescent checkpoint or an already-quiescent stop, no such process
remains. Preserve the status output and runtime evidence when stopping because of an
unexpected condition.

Common signals and the safe response:

| Signal | Meaning | Safe response |
|---|---|---|
| `READY` | A reviewed next action may be available. | Recheck ticket, tree, and quota before `run` or `resume`. |
| `HUMAN_GATE` / `PERIODIC_CHECKPOINT` | Human review is required. | Do not bypass it; follow its documented release procedure. |
| quota blocked or unknown | No authorization exists. | Supply a fresh trusted manual observation or stop. |
| `VERIFICATION_FAILED` | A deterministic check failed. | Preserve its log; use only the explicit same-ticket recovery route when offered. |
| `SCOPE_BLOCKED`, `GIT_BLOCKED`, or ownership conflict | Guard prevented an unsafe action. | Do not edit state or force Git; investigate and reconcile through the named process. |
| `SUPERVISOR_REPAIR_FAILED` | A controller repair was not authorized or did not complete safely. | Preserve evidence and use a separately approved controller change. |

## Recovery and advanced contracts

Recovery is evidence-driven. Do not delete locks, quota records, run artifacts,
bindings, archives, or state to make a command proceed. For an unchanged generic
`VERIFICATION_FAILED` checkpoint, only the explicit audited same-ticket recovery may
validate the exact checkpoint, one currently configured failed check, and its durable
log. That validation invokes no model and consumes no quota; any subsequent repair must
pass the full verification, scope, and commit gates.

`./dev recover-protected-snapshot` is a narrow historical recovery command, not a
general override. Use it only when its own status conditions prove the protected-control
snapshot defect; it checks the exact ticket, runs, HEAD, branch, dirty bytes, reports,
artifacts, quota audit, product snapshot, and complete Git fingerprint. Any mismatch
leaves the checkpoint unchanged.

An engine update is staged as a separate immutable generation. Verify identity,
compatible versions, dry-run migration, and tests away from the active controller;
switch only at quiescence with an archive, then reconcile read-only. A stale host or
unsupported state makes no write. Rollback first stops the new generation and restores
the archived predecessor through the documented command. Retain archives and recovery
receipts; current documentation cleanup never deletes them.

Legacy migration is opt-in and is rehearsed only on an isolated copy. It requires a
supported quiescent source, an explicit dry run, a recorded source checksum, a human
go/no-go, and read-only reconciliation after the binding handoff. On no-go, stop the
candidate at a quiescent point and use the documented rollback. Never hand-edit an
archive, binding, policy, state, quota ledger, or lock to force migration or rollback.

## Authority, commits, and push

Configuration is versioned and validated before a model, Git mutation, or remote
operation. `self_modification`, `user_requested_modification`, and `repository_push`
are independent and disabled by default. Repository content may restrict a host grant,
but cannot enable one. Invalid, contradictory, missing, or unknown configuration fails
closed.

The verified ticket commit is local until a separately enabled push capability confirms
it on the configured remote and branch. Never infer authority from a Git default or
repository policy. Do not force-push or rewrite history. A failed push preserves the
local commit and is not completed persistence.

## Keep these habits

- Inspect `./dev status` before every consequential command.
- Keep one writer and do not assume Git synchronization is a runtime lock.
- Preserve checkpoints and evidence; do not use cleanup commands to hide a mismatch.
- Stop when a request broadens scope or changes architecture without approval.
- Keep credentials, account data, runtime artifacts, and unredacted evidence out of
  commits.
- Run `python3 scripts/check_documentation.py` after a reviewed guide update.

For policy and implementation details, use the reviewed documents named by the active
plan and ticket. Historical 1.x and completed 2.0 material is retained in Git history,
not as a current operator instruction.
