# Supervisor 2.1 development candidate

Status: **approved scope input — implementation requires a separately materialized
plan epoch**.

This candidate updates the 2026-09-25 discussion after the successful Supervisor 2.0
cutover. None of this work is retrofitted into the released 2.0 lineage. The existing
1.x engine and checksummed cutover archive remain preserved as recovery evidence; Git
history is not rewritten.

## Outcomes

### Clear, current, neutral documentation

- Keep the English operator guide as the normative guide and make it understandable
  without prior knowledge of the internal architecture.
- Rewrite the maintained Russian operator guide as a clear operational counterpart,
  reviewing it section by section against the English guide rather than mechanically
  translating internal terminology.
- Retain a small translation manifest for the single EN/RU pair. It is useful as a
  deterministic freshness alarm, but it must continue to say that semantic
  equivalence is not machine-asserted.
- Reduce the default branch to current user documentation, concise invariants and
  trust boundaries, current migration guarantees, current backlog, schemas, and
  executable tests. Historical 1.x narratives and completed 2.0 ticket specifications
  may be removed only after their still-current guarantees and recovery routes have
  been preserved elsewhere. The 2.0 tag and Git history are the archive.
- Remove project-specific names, private host details, and personal wording from the
  current public tree. Do not rewrite published Git history.

### Automatic Codex quota observations

- Add a capability-detected provider for `account/rateLimits/read`.
- Start a fresh short-lived Codex app-server for every observation; do not attach to
  or reuse an already running daemon.
- Identify five-hour and weekly buckets by window duration, normalize only current
  usage, record source/account/protocol identity, and preserve authorization audit.
- Treat `ordinaryUsageAllowed=false`, missing or ambiguous buckets, protocol errors,
  unavailable executables, and authorization failures as non-permission. Fall back to
  the existing explicit manual observation workflow.
- Use a fake JSON-RPC app-server for deterministic tests. No network/account access is
  allowed in the unit suite.

### Neutral compatibility and self-hosted acceptance

- Replace project-specific compatibility inputs with a compact, synthetic,
  checksummed legacy 1.x fixture.
- The neutral predecessor is the exact commit produced by the first 2.1 documentation
  and public-neutralization ticket. Record its hash in the later acceptance artifact;
  do not guess the hash in advance.
- Run the current Supervisor against an isolated checkout of that predecessor. Cover
  bounded no-change, repeated failure, unavailable/contradictory quota, interrupted
  authorization, repeated resume, commit-boundary, and unchanged recovery scenarios.
- Every scenario has a hard invocation limit, an expected quiescent or terminal state,
  and assertions against duplicate model calls, commits, and quota consumption.

### Platform scope

- Keep Linux as the qualified host for 2.1.
- Perform deterministic portability review and simulated platform-contract tests, but
  perform no check on a real Mac in this cycle and make no macOS support claim.
- Record real-device macOS qualification as deferred work rather than silently
  treating simulated checks as qualification.

### Real Codex acceptance

- After the automatic provider and deterministic self-hosted suite pass, and before
  the 2.1 release gate, run at least one isolated acceptance workflow with the locally
  installed real Codex.
- Bound the run by explicit model-call and time limits, use ordinary quota
  authorization, keep it separate from live project state, and preserve a redacted
  acceptance receipt. It is an operator-owned qualification step, not a networked CI
  test.

## Proposed dependency order

1. `T20` — current documentation, Russian rewrite, public neutralization, and
   retirement rules. Its verified commit becomes the neutral predecessor.
2. `T21` — short-lived app-server quota provider and manual fallback.
3. `T22` — generic legacy fixture and bounded self-hosted acceptance matrix, pinned to
   the exact `T20` predecessor commit.
4. `T23` — deterministic portability hardening with real-Mac qualification explicitly
   deferred and macOS still unsupported.
5. `T24` — one real Codex acceptance run, final documentation reconciliation, and the
   human 2.1 release decision.

## Non-goals

- rewriting published Git history;
- re-releasing or changing the 2.0 cutover lineage;
- reusing a persistent app-server daemon for quota observations;
- real-device Mac testing or a macOS support claim in 2.1;
- project-specific compatibility branches in the public Supervisor;
- an unbounded live-model acceptance loop.
