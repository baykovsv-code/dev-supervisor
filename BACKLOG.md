# Development Supervisor backlog

The current approved work is [Supervisor 2.1](docs/backlog/supervisor-2.1.md). Its
dependency order is T20 → T21 → T22 → T23 → T24. The current operator entry point is
[the English guide](docs/operator-guide.md), with its reviewed Russian counterpart.

## Current safety baseline

- Repository content and model output cannot grant capabilities or approve their own
  architecture.
- One managed repository has one writer and one immutable active engine generation.
- Unknown quota, protocol, platform, state, ownership, or compatibility is not
  permission.
- Retries are bounded and idempotent across invocation, authorization, verification,
  commit, and resume boundaries.
- Historical Git objects and host-local recovery archives are distinct. Documentation
  cleanup changes neither.
- Linux is qualified. No real Mac was tested, and macOS is unsupported.

## Current delivery rules

- English operator material is normative. The Russian guide is reviewed with the final
  English source; its manifest is a freshness alarm only and makes no semantic claim.
- Published history is not rewritten. Ignored runtime archives and engine checkouts are
  never documentation-cleanup targets.
- A verified local commit is not remote persistence. Push is separately enabled and
  confirmed against the configured remote and branch.
- The exact verified T20 commit is recorded through ordinary ticket-completion evidence
  as T22's immutable predecessor; no commit hash is predicted in planning material.
- 2.1 performs no real-Mac test and makes no macOS support claim.
