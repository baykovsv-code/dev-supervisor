# T07: Observed quota range policy

## Objective

Implement the deterministic observed-quota policy in R09 without forecasting.

## Scope

- Add configured high, medium, and low/unknown ranges by applicable window and role.
- Bound high-range reuse by TTL and invocation count.
- Require a fresh trusted observation per medium-range call and block low/unknown.
- Invalidate on rate/usage signals, provider/model/account change, TTL, count, or
  contradictory data.
- Reconcile crash boundaries without double consumption and expose the decision audit.
- Remove quota forecast inputs and outputs.

- Files/modules: `supervisor.py`, `schemas/`, `tests/`.

## Acceptance criteria

- Boundary, TTL, reuse exhaustion, crash, and rate-limit tests are deterministic.
- Every model call links to the exact authorizing observation.
- No reset-time, future balance, ticket count, or quota availability prediction exists.
- Unknown or malformed data starts no model process.

## Non-goals

- scraping provider UI;
- predicting reset behavior.
