# Development Supervisor operator guide

This is normative English operator material for the implemented T01-T10 behavior and
the practical bootstrap arrangement. It explains what is safe to run, what must remain
pinned, and what requires a human decision. The architecture and approved ticket
acceptance criteria remain the controlling design record. The maintained Russian
operator translation is [operator-guide.ru.md](operator-guide.ru.md); English is the
sole complete normative documentation set. See [documentation governance](documentation-governance.md)
for pairing, freshness, and legacy-evidence rules.

## Current controller topology

| Purpose | Path | Revision / state |
|---|---|---|
| Pinned legacy controller that develops Supervisor 2.0 | `/home/dev/Documents/dev-supervisor-old` | Supervisor 1.x AS-IS |
| Supervisor 2.0 development repository | `/home/dev/Documents/dev-supervisor` | `main`; managed by the legacy controller |
| Immutable engine used by live personal-assistant | `/home/dev/Documents/dev-supervisor-runtime-1x` | detached commit `41f6757` |
| Live managed product | `/home/dev/Documents/personal-assistant` | T30 `HUMAN_GATE` |

The two controller relationships are separate:

```text
dev-supervisor-old -> develops dev-supervisor
dev-supervisor-runtime-1x -> controls personal-assistant
```

The development checkout is not executable authority for live `personal-assistant`.
This prevents a development commit from hot-changing the engine in the middle of a
product run.

## Safe read-only checks

Check the Supervisor 2.0 development project:

```bash
cd /home/dev/Documents/dev-supervisor
./dev status
```

Expected before T00 starts:

- state `READY`;
- current ticket `T00`;
- clean working tree;
- unknown quota until a fresh observation is supplied.

Check live personal-assistant:

```bash
cd /home/dev/Documents/personal-assistant
./dev status
```

Expected until the owner finishes T30 evidence:

- state `HUMAN_GATE`;
- current ticket `T30`;
- the preserved nine-file dirty checkpoint;
- engine root `/home/dev/Documents/dev-supervisor-runtime-1x`.

`status` is read-only. An unexpected state, HEAD, engine path, or file list closes the
gate: stop and investigate before running `resume`, setting quota, or editing files.

## Quota authorization

Only copy values from a current trusted interactive Codex `/status` observation:

```bash
./dev quota set --five-hour <percent> --weekly <percent>
```

The weekly value may be omitted only when it is genuinely unavailable and policy
allows that observation shape. Never guess percentages or reset times. A model call
consumes its authorization; diagnostic, recovery, and repair roles can require another
fresh observation.

Setting quota does not approve architecture, release a human gate, authorize push, or
permit self-repair.

## Supervisor 2.0 operating contract through T10

Configuration is versioned and validated before a model, Git mutation, or remote
operation. The independent `self_modification`, `user_requested_modification`, and
`repository_push` capabilities are disabled by default and fail closed. A repository
policy can further restrict a host/operator grant, but repository content and prompts
cannot enable a capability. Effective configuration exposes provenance while redacting
secrets. Unknown keys, unsupported versions, invalid ranges, contradictory values, or
missing grants stop the operation.

The durable lifecycle is assessment, requirements review, architecture review, plan
ready, ticket execution, plan completed, backlog review, then an approved new plan
epoch. Approvals name exact document versions. Completion of a final ticket is
reconciled idempotently into `PLAN_COMPLETED`; it never starts a model or chooses more
work. A backlog item becomes executable only after bounded selection, requirements and
dependency analysis, architecture-impact review, human approval, and a new immutable
plan epoch. State, approvals, epochs, engine identity, and audit events are versioned;
unknown, unsupported, ambiguous, or newer forms stop without an implicit rewrite.

Existing-project admission is read-only to product code. A project without an
architecture receives an external-architecture requirement and admission checklist;
foreign-format documents receive compatibility findings and a mapping/gap manifest.
Supervisor is not adapted to fit the project, and no compatible plan/index is created
until the source baseline is reviewed and approved.

For an explicitly requested bounded improvement, preserve the trigger, perform an
architecture-impact review, obtain approval, use a bounded plan/ticket, verify, and
escalate to the ordinary cycle if bounds fail. Self-development follows that same
workflow but produces a successor in an isolated checkout. The generation currently
controlling a run stays immutable. Activation is a separate, quiescent, human-approved
handoff with rollback; two controller generations never control the same project.

Quota is based only on trusted current observations: high observations can authorize a
bounded number of calls within their TTL, medium observations require a fresh snapshot
per call, and low or unknown observations block. Every invocation has an audit record.
There is no quota/reset/capacity forecast and no `forecast.fallback_ticket_hours`
configuration or migration.

For a generic unchanged `VERIFICATION_FAILED` checkpoint, do not rerun the failed
check. An explicit audited same-ticket recovery first validates the exact model
checkpoint, exactly one currently configured failed check, and its durable log. This
validation alone invokes no model and consumes no quota. The repair then passes the
full verification suite and ordinary scope and commit gates. Missing, altered, stale,
or ambiguous evidence fails closed; mandatory host verification follows its stricter
handling.

An engine update uses a separately staged immutable identity with compatible
configuration/state/protocol ranges. Verify, dry-run migration, and test it away from
the active controller; archive and switch only at quiescence; then reconcile
read-only. A stale host or incompatible state makes no write. Rollback stops the new
generation before restoring the archived predecessor.

## Developing Supervisor 2.0

Do not start T00 until the requirements index, architecture, plan, and ticket set have
human approval.

After approval and a fresh quota observation:

```bash
cd /home/dev/Documents/dev-supervisor
./dev quota set --five-hour <percent> --weekly <percent>
./dev run
```

T00 creates the redacted `personal-assistant` compatibility fixture and no-model
harness. Every implementation ticket through T11 in authoritative plan order must
then pass that harness as part of the normal test suite. Intermediate revisions are
tested only on isolated copies; they are never bound to live `personal-assistant`.

Before every run:

1. inspect `./dev status`;
2. confirm the working tree is clean or exactly matches a recorded recovery checkpoint;
3. confirm the current ticket and expected role;
4. read the current ticket and any displayed gate;
5. supply fresh quota only when ready for that exact invocation.

Do not run T99. The milestone after T12 is the final human cutover gate and must not be
released under Supervisor 1.x.

## Periodic checkpoints between tickets

Supervisor can stop between completed tickets when a configured periodic threshold is
reached, for example:

```text
State: PERIODIC_CHECKPOINT
Ticket: T02
2 completed tickets reached the limit of 2
resume_command: null
```

This is a successful bounded stop, not a failed ticket and not a quota checkpoint. The
previous ticket has already passed verification/scope and has been committed; the next
ticket has not started. `safe_to_power_off: true` means no model or verification
process remains active.

`resume_command: null` is decisive: an ordinary `./dev resume` must not cross this
human gate. It will return the same `PERIODIC_CHECKPOINT` state. Likewise,
`./dev quota set ...` only records a quota observation; it does not approve or release
the checkpoint.

Review before release:

```bash
cd /home/dev/Documents/dev-supervisor
./dev status
git status --short --branch
git log --oneline --decorate -5
```

Confirm that:

- the working tree is clean;
- the reported HEAD equals the last successful ticket commit;
- the expected tickets are completed and the next ticket is correct;
- verification and compatibility tests passed;
- no plan, architecture, scope, or operator decision needs correction.

When no plan change is needed, release the gate with a meaningful review note:

```bash
./dev gate release --note "Reviewed T00-T01: commits and verification passed; tree clean; T02 may start"
```

Then ensure quota is still fresh. If status reports `Quota: OK` and the observation has
not expired, the observation recorded while the gate was closed remains available. If
it is missing, stale, or no longer trusted, record a new observation:

```bash
./dev quota set --five-hour <percent> --weekly <percent>
```

Finally continue the newly released `READY` state:

```bash
./dev resume
```

If review discovers a legitimate plan or architecture change, do not use an ordinary
release note to bypass it. Keep the checkpoint closed and use the documented plan
reconciliation/architecture-adoption workflow. If HEAD or the working-tree fingerprint
changed after the checkpoint, gate release must fail closed; investigate rather than
resetting or cleaning the tree.

## Completing personal-assistant T30

T30 requires an owner-authenticated live PASS/FAIL test. Automated checks cannot
substitute for that evidence.

Safe sequence:

1. Keep `personal-assistant` at the T30 `HUMAN_GATE` while preparing the real test.
2. Perform the documented browser/account/network/restart/source/link checks.
3. Record the dated, redacted result in the existing T30 evidence file.
4. Confirm `./dev status` still reports the expected checkpoint.
5. Release the gate only when the recorded evidence is complete:

```bash
cd /home/dev/Documents/personal-assistant
./dev gate release --note "T30 owner evidence recorded: PASS/FAIL, date, concise basis"
./dev resume
```

Do not release the gate merely because the prepared code or synthetic checks pass. Do
not clean, reset, stash, or manually commit the preserved T30 files outside the
documented gate workflow.

## Self-repair behavior for live personal-assistant

Supervisor 1.x has no real configuration switch for disabling bounded self-repair.
The pinned runtime therefore contains this deliberate untracked guard:

```text
/home/dev/Documents/dev-supervisor-runtime-1x/.self-repair-disabled
```

Do not remove it.

If diagnostics classify a failure as `SUPERVISOR_BUG`:

1. the workflow reaches `SUPERVISOR_REPAIR_PENDING`;
2. a separate fresh quota observation is required before a repair model could run;
3. the runtime repository cleanliness check sees the guard file;
4. no repair model starts and no repair quota authorization is consumed;
5. state becomes `SUPERVISOR_REPAIR_FAILED`;
6. product work remains preserved, and no Supervisor code, product commit, or remote
   ref is changed.

`./dev resume` does not bypass `SUPERVISOR_REPAIR_FAILED`. The safe response is:

1. stop automation and preserve the product checkpoint;
2. inspect diagnostic state and run artifacts;
3. reproduce the defect in `/home/dev/Documents/dev-supervisor`;
4. implement it through an approved Supervisor ticket;
5. pass the full suite and personal-assistant compatibility harness;
6. create a new immutable engine checkout;
7. switch the live binding only through a reviewed quiescent cutover with rollback.

Never "fix" this state by deleting `.self-repair-disabled` or pointing the live project
at the mutable development checkout.

## Commit ownership and timing

The default rule is: the Supervisor owns implementation commits. After a ticket model
passes verification and scope checks, the Supervisor creates the ticket commit and
records that exact commit in runtime state. Do not pre-commit, amend, squash, rebase, or
replace that work manually.

### When a manual commit is allowed

A manual operator commit is allowed only in one of these situations:

1. The project is quiescent in `READY`, with `active_run: null`, `pending_commit: null`,
   no gate, and a clean working tree before the edit. The change must be an explicitly
   reviewed operator/control/documentation change outside an implementation ticket.
2. A documented human or architecture gate explicitly requires a human-authored commit
   and provides the matching adoption/reconciliation command.
3. A reviewed migration/bootstrap procedure explicitly calls for a local commit before
   the first managed run.

For a small operator-documentation change between tickets, use this sequence:

```bash
./dev status
git status --short --branch
# edit only the reviewed file
git diff --check
git diff -- docs/operator-guide.md
git add docs/operator-guide.md
git commit -m "Document periodic checkpoint operation"
./dev status
```

The pre-commit status must show `READY`; the post-commit status must still show the
same current ticket, a clean tree, and no unexpected gate/run. Stage exact paths rather
than using broad `git add .` in a repository with preserved or unrelated work.

### When a manual commit is forbidden

Do not manually commit, amend, rebase, stash, reset, or clean when:

- a model, verification command, scope check, or Supervisor commit is active;
- state is `IMPLEMENTING`, `VERIFYING`, `SCOPE_PENDING`, `COMMITTING`,
  `RECOVER_MODEL`, or another non-quiescent phase;
- a `PERIODIC_CHECKPOINT` or `HUMAN_GATE` is still closed, unless that exact gate
  explicitly requires a human-authored commit;
- the working tree is a recorded recovery, evidence, interrupted, or diagnostic
  checkpoint;
- `active_run` or `pending_commit` is present;
- files belong to live T30 evidence or another preserved product checkpoint;
- the proposed commit changes architecture/plan/scope without the corresponding human
  approval and reconciliation workflow.

In particular, do not commit documentation while a periodic checkpoint is closed.
Release and verify the gate first; then make the documentation commit from `READY`
before starting the next ticket.

### Commit contents that are never allowed

Never commit:

- `.dev-supervisor/` runtime state, quota observations, locks, run artifacts, or local
  engine bindings;
- credentials, access tokens, account/browser data, or unredacted live evidence;
- `/home/dev/Documents/dev-supervisor-runtime-1x/.self-repair-disabled` or other files
  from the pinned runtime checkout;
- unrelated dirty files merely to obtain a clean status;
- generated changes outside the current ticket's reviewed scope.

After Supervisor-created commits, preserve their identities because runtime lineage
references them. Do not amend, squash, rebase, cherry-pick over, or force-push those
commits while the managed lifecycle is active. If history must change, stop and use a
separately reviewed recovery/migration procedure.

## Git and push

Normal checks:

```bash
git status --short --branch
git log --oneline --decorate -5
git diff --check
```

Push is an explicit operator action during the 1.x bootstrap. Neither a local commit
nor model output authorizes it automatically. Before pushing:

1. confirm the intended repository, remote, and branch;
2. inspect the exact commits that are ahead of the remote;
3. confirm tests and gates passed;
4. ensure no credentials or runtime artifacts are tracked;
5. use a normal fast-forward push.

```bash
git push origin main
```

Do not force-push, rewrite history, or treat a failed push as completed remote
persistence. Never push from `personal-assistant` merely to resolve a Supervisor gate.

## Things to avoid

- Do not bind live `personal-assistant` to `/home/dev/Documents/dev-supervisor` during
  T00-T12 development.
- Do not edit files inside `/home/dev/Documents/dev-supervisor-runtime-1x`.
- Do not remove `.self-repair-disabled`.
- Do not run two controllers against the same managed repository.
- Do not release T30 without real owner evidence.
- Do not supply invented or stale quota values.
- Do not use `git reset --hard`, cleanup commands, or manual commits on a preserved
  recovery/evidence checkpoint.
- Do not run T99 or release the post-T12 gate under Supervisor 1.x.
- Do not migrate live state directly; rehearse on an isolated copy first.
- Do not assume Git synchronization provides a runtime lock or engine compatibility.

## Stop conditions

Stop without guessing when any of the following occurs:

- engine root, branch, HEAD, current ticket, or gate differs from the expected value;
- state, policy, or compatibility version is unknown;
- the working tree differs from the recorded checkpoint;
- a model asks to broaden scope or change architecture without approval;
- `SUPERVISOR_REPAIR_FAILED`, `GIT_BLOCKED`, `SCOPE_BLOCKED`, or an unsupported
  migration state is reported;
- the same managed repository may be writable from another host/controller;
- a push would be non-fast-forward or require bypassing branch protection.

Preserve state and artifacts, record the exact status output, and resolve the condition
through the appropriate architecture, product, or operator gate.

## Key references

- [Requirements index](architecture/requirements-index.md)
- [Proposed architecture](architecture/architecture.md)
- [Implementation plan](architecture/implementation-plan.md)
- [Migration analysis](architecture/migration-analysis.md)
- [T00 compatibility isolation](architecture/tickets/00-isolate-runtime-and-compatibility-harness.md)
- [Russian AS-IS quickstart](quickstart.ru.md)
- [Russian AS-IS limitations](limitations.ru.md)
