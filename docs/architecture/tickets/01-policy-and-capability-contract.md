# T01: Versioned policy and capability contract

## Objective

Add a versioned, preflight-validated configuration contract and the authority model
required by R06/R10 before adding any new mutation path.

## Preconditions

- The human gate has approved `requirements-index.md`, `architecture.md`, this plan,
  and the ticket set as one baseline.
- Supervisor 1.x regression tests pass unchanged at the starting commit.

## Scope

- Define schemas and validation for project configuration and host-controlled
  capability grants.
- Add independent `self_modification`, `user_requested_modification`, and
  `repository_push` capabilities, all defaulting and failing closed to disabled.
- Combine repository restrictions with host grants by intersection; repository or
  prompt content cannot elevate authority.
- Expose effective redacted configuration and provenance in status/audit.
- Reject unknown keys, unsupported versions, contradictions, and invalid ranges
  before model or Git mutation.
- Remove `forecast.fallback_ticket_hours` from the new contract without a shim.

- Files/modules: `supervisor.py`, `schemas/`, `tests/`.

## Acceptance criteria

- Missing or malformed capability values deny the action.
- Each capability is independently testable and one grant never implies another.
- A repository commit attempting to enable a capability is ineffective without the
  operator-controlled grant.
- Legacy policy import reports the removed forecast field but does not preserve it.
- Existing 1.x fixtures have an explicit compatibility/migration result.

## Non-goals

- implementing self-development, user improvement, or push;
- storing credentials or grants in the managed repository.
