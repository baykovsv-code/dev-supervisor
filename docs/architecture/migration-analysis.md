# AS-IS extraction and controller-chain analysis

Date: 2026-09-24

## Decision

No stop-factor prevents an AS-IS extraction into `dev-supervisor`. The development
checkout must not remain the live `personal-assistant` engine while tickets modify it;
a separate immutable AS-IS runtime checkout and rolling compatibility gate resolve that
risk.

## Evidence reviewed

- all 1.x engine files, launchers, prompts, schemas, policy defaults, and 156 tests;
- Russian AS-IS architecture, state-machine, principles, limitations, quickstart, and
  summary documents;
- the 2.0 backlog and migration RFC;
- the existing `dev-supervisor` Git history and `BACKLOG.md`;
- the live `personal-assistant` policy, engine binding, runtime state, Git state, and
  implementation plan.

## Baselines

- legacy engine: `854083f51c9aedf33ec2d9654fc67aacff84af8a`;
- new repository before extraction:
  `dfb946c0096a2789272a76e4cc33bb0882c8745b`;
- personal-assistant at inspection:
  `68e51070ef44c4942c0b9eac049324165f3ef04c`.

The 1.x regression suite passed: `Ran 156 tests ... OK`. Engine-owned executable files
are copied byte-for-byte before any 2.0 ticket.

## Resolved findings

1. `personal-assistant/.dev-supervisor/engine.json` already points to
   `/home/dev/Documents/dev-supervisor`, but that repository initially lacked
   `supervisor.py`. This alone caused `./dev status` to fail with
   `FileNotFoundError`; AS-IS extraction restores the referenced engine.
2. `personal-assistant` is deliberately dirty at the T30 evidence gate. Its state is
   `HUMAN_GATE`, there is no pending commit and no active supervisor/Codex process.
   The dirty files match the preserved T30 checkpoint and must not be cleaned,
   committed, or rewritten by migration.
3. The old controller can manage the new repository because engine and managed-project
   roots are distinct. The live `personal-assistant` engine is separately pinned to a
   detached AS-IS checkout, so development commits do not hot-change it.
4. Intermediate 2.0 revisions are tested only against an isolated copy of the T30
   checkpoint. They never become live merely because a ticket commit passed.
5. Supervisor 1.x has no push operation and no configuration switch that disables
   bounded self-repair. During this bootstrap it is treated as a pinned local
   controller; pushes are manual and out of scope, and any requested supervisor repair
   is a stop requiring human review.
6. The existing GitHub persistence backlog item is compatible with default-off push
   only when remote completion semantics apply after explicit capability enablement.

## Files transferred as historical AS-IS material

- `docs/architecture-as-is.ru.md`
- `docs/state-machine.ru.md`
- `docs/principles.ru.md`
- `docs/limitations.ru.md`
- `docs/quickstart.ru.md`
- `docs/backlog/supervisor-as-is-and-usage-ru.md`

The Russian 2.0 backlog and migration RFC remain in the legacy repository as source
material. Their normalized 2.0 requirements are represented by the English
requirements index and proposed architecture in this repository.

## Human qualification sequence

1. Confirm the new repository is clean and `./dev status` reports T00 without invoking
   a model.
2. Review and approve the English requirements, architecture, plan, and tickets.
3. Confirm `personal-assistant/.dev-supervisor/engine.json` names the detached AS-IS
   runtime checkout, then run `./dev status` and verify T30, `HUMAN_GATE`, unchanged
   HEAD, state checksum, and preserved nine-file checkpoint.
4. Exercise only the documented T30 human evidence workflow through that pinned
   runtime; development of `dev-supervisor` cannot change its engine files.
5. Run T00 through the old controller to create the redacted fixture and compatibility
   harness. Every later ticket must pass it automatically.
6. Use only isolated copies for candidate-engine tests until T12. Change the live engine
   binding only at the final human cutover gate.

Failure of any identity, state, fingerprint, status, or non-overlap check closes the
gate and requires investigation before a model run.
