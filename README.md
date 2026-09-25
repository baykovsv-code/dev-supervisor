# Development Supervisor

Development Supervisor is a conservative, standalone controller for a Git
repository. It is a plain Python program: no package installation, service, or plugin
framework is required. A controlled repository uses a small `./dev` launcher while
its policy and ignored runtime state remain in that repository.

Start with the [operator guide](docs/operator-guide.md). It covers installation,
ordinary work, gates, safe stopping, and recovery. The English guide is normative;
the reviewed Russian operational counterpart is
[available in Russian](docs/operator-guide.ru.md).

## Requirements

- Python 3
- Git
- the configured Codex CLI, when a policy authorizes a model invocation

Linux is the qualified platform. No real Mac was tested for this release; macOS is
unsupported. See the guide before attempting to use another platform.

## Install a controller in a repository

From an engine checkout, initialize a repository you control:

```bash
./supervisor init /path/to/project
```

For a project that already has reviewed policy, provide it explicitly:

```bash
./supervisor init /path/to/project --policy /path/to/policy.json
```

Initialization creates the launcher, checked-in policy, ignored `.dev-supervisor/`
runtime directory, and minimal planning material when the default policy is used. It
will not overwrite a conflicting control surface. Review and commit the generated
tracked files before the first run.

## Useful checks

```bash
./dev status
python3 scripts/check_documentation.py
python3 -m unittest discover -s tests -v
python3 -m py_compile supervisor.py
git diff --check
```

Documentation pairing, links, and freshness are governed by
[documentation governance](docs/documentation-governance.md). The retained migration
and rollback guarantees are summarized in the operator guide; historical material is
recoverable from Git history and is not a current runbook.
