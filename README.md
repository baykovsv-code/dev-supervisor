# Development supervisor

A standalone, conservative development supervisor for Git repositories. It remains a
plain Python program: there is no package build, installation step, importable SDK, or
plugin framework. Controlled repositories keep their own policy and runtime state and
invoke this repository through a lightweight `./dev` launcher.

Requirements: Python 3, Git, and `codex-cli 0.155.1`.

## Initialize a repository

From this repository:

```bash
./supervisor init /path/to/project
```

For an existing controlled project with an established policy:

```bash
./supervisor init /path/to/project --policy /path/to/policy.json
```

Initialization adds only the currently required control surface:

- executable `dev` launcher;
- checked-in `dev-supervisor.json` project policy;
- ignored `.dev-supervisor/` runtime with engine binding and initial state;
- `.dev-supervisor/` entry in `.gitignore`;
- for default initialization only, a minimal T01 plan and ticket scaffold.

It refuses to overwrite an existing launcher, policy, or conflicting default planning
files. Review and commit the generated tracked files before the first model run.

The launcher resolves the engine from `.dev-supervisor/engine.json`. Set
`DEV_SUPERVISOR_HOME` to override that local binding after moving or recloning this
repository.

## Normal operation

The project-facing syntax is unchanged:

```bash
./dev status
./dev quota set --five-hour 50
./dev run
./dev resume
./dev stop
```

All existing subcommands, gates, recovery paths, and quota behavior remain owned by
`supervisor.py`. Project state and run evidence stay under the project's ignored
`.dev-supervisor/` directory. Project-specific tickets, verification commands,
allowlists, milestones, and models stay in `dev-supervisor.json`.

## Repository boundaries

The engine repository owns:

- `supervisor.py`;
- `prompts/` and `schemas/`;
- regression tests;
- the standalone `supervisor` launcher and documentation.

A controlled project owns only its launcher, policy, product files, planning documents,
and runtime state. The engine never copies itself into a controlled repository.

When a validated `SUPERVISOR_BUG` diagnosis reaches bounded self-repair, the model runs
inside this engine repository. Only existing engine/documentation/test paths are
allowed, the controlled project's product fingerprint must remain unchanged, engine
tests and compilation must pass, and the resulting commit is created in this repository.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile supervisor.py
git diff --check
```

The extraction scope and compatibility guarantees are recorded in [MIGRATION.md](MIGRATION.md).
