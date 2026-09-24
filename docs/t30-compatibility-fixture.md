# T30 compatibility fixture

`tests/fixtures/t30-compatibility/` is the redacted, checksummed structural fixture
used by the normal unittest suite. It contains no credentials, personal content, live
paths, host-specific identifiers, or live Git object IDs. The test materializes its
own temporary Git repository and runtime directory; it never reads or writes a live
`personal-assistant` checkout.

The fixture retains the compatibility-relevant T30 shape: a path-only `engine.json`
binding (whose candidate path is materialized only in the temporary copy), legacy
policy and state formats, the closed `HUMAN_GATE`, quota-observation identity, a T30
run-evidence directory, plan frontier, and both tracked and untracked product work.
`state.json` uses explicit product-head and fingerprint placeholders because those
values are created afresh in the isolated Git repository.

## Operator evidence

The precondition evidence remains operator-owned and outside this development
checkout: the live `personal-assistant` binding points at detached engine revision
`41f6757`, and a read-only `./dev status` records the unchanged T30 `HUMAN_GATE`.
Ticket work must neither edit that project nor the detached checkout. The fixture is
not activation authority and does not release the evidence gate.

## Refresh procedure

Only a reviewed, redacted structural snapshot with recorded provenance may replace
this fixture. The reviewer must confirm that it preserves the supported launcher,
policy/state versions, closed gate and quota identities, plan frontier, run-evidence
shape, and dirty-product semantics while removing credentials, personal content,
absolute live paths, and live Git identities.

For a proposed replacement:

1. Prepare and review the redacted snapshot outside the live project and detached
   engine checkout.
2. Record the source checkpoint, redaction review, reviewer, and date in the change
   review; do not put sensitive source data into this repository.
3. Recompute SHA-256 values for every tracked fixture input and update
   `checksums.json` in the same reviewed change.
4. Run the discovered test suite. A checksum mismatch, an unsupported legacy load, a
   state/evidence mutation, a product change, or a model/network subprocess is a
   failure.

Fixture replacement is a compatibility-baseline change and requires explicit review;
it is never an automatic refresh from a live runtime.
