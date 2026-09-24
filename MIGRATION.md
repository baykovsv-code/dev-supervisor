# Standalone extraction

## Scope

Extract the existing repository-embedded development supervisor into an independent
Git repository without turning it into a package and without adding future or
speculative orchestration features.

## Required compatibility

- Preserve the project-facing `./dev <command>` syntax.
- Use lightweight launchers instead of installing a Python package.
- Keep policy, status/state, quota, run artifacts, and locks local to each controlled
  repository.
- Provide one `init` command that installs the launcher, policy, ignored runtime binding,
  initial state, and the minimum planning structure required today.
- Preserve bounded supervisor self-repair, but run and commit it in the engine repository
  without allowing product changes in the controlled repository.
- Preserve the active controlled-repository state and its ability to continue from an
  existing human gate.

## Implemented boundary

`supervisor.py`, prompts, schemas, tests, and engine documentation live here. A
controlled repository contains `dev`, `dev-supervisor.json`, and ignored
`.dev-supervisor/` runtime data. The launcher records no project behavior; it locates
this engine, identifies the project root, and delegates unchanged CLI arguments.

A one-time extraction commit in an already-controlled repository may be treated as a
control-plane-only descendant of its preserved checkpoint. Product files and the
existing runtime state are not moved, rewritten, or reset.

## Deliberate non-goals

- packaging or publishing;
- a plugin system;
- remote engine discovery or automatic updates;
- new model roles, ticket semantics, gates, or product features;
- generalized configuration beyond separating existing project-owned and engine-owned
  files.
