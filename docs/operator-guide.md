# Development Supervisor operator guide

This is the practical runbook for the current bootstrap arrangement. It explains what
is safe to run, what must remain pinned, and what requires a human decision. It does
not replace the authoritative architecture or ticket acceptance criteria.

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
harness. Every T01-T11 ticket must then pass that harness as part of the normal test
suite. Intermediate revisions are tested only on isolated copies; they are never bound
to live `personal-assistant`.

Before every run:

1. inspect `./dev status`;
2. confirm the working tree is clean or exactly matches a recorded recovery checkpoint;
3. confirm the current ticket and expected role;
4. read the current ticket and any displayed gate;
5. supply fresh quota only when ready for that exact invocation.

Do not run T99. The milestone after T12 is the final human cutover gate and must not be
released under Supervisor 1.x.

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
