# Personal-assistant T12 qualification and cutover runbook

This is the normative English T12 runbook. It qualifies only an isolated copy of
the redacted T30 `HUMAN_GATE` source. It neither authorizes a live cutover nor
releases the owner's T30 evidence gate. The maintained Russian operator workflow is
in [operator-guide.ru.md](operator-guide.ru.md); where the texts differ, this English
document controls.

## Scope and retained source fixture

The sole supported predecessor source is the exact 1.x version-4 `HUMAN_GATE`: no
active model/check/commit control, an unambiguous gate ticket, and a gate
HEAD/fingerprint that matches the isolated product. The redacted structural copy and
its SHA-256 inventory are [the T30 compatibility fixture](t30-compatibility-fixture.md)
and [`checksums.json`](../tests/fixtures/t30-compatibility/checksums.json). It retains
the path-only binding, policy/state and quota-ledger versions, T30 run-evidence shape,
and tracked/untracked product work without live identity, credentials, personal data,
or live Git objects.

The live product and its immutable AS-IS engine are evidence-only inputs. Do not run
these commands in `/home/dev/Documents/personal-assistant`, do not copy runtime data
out of it, and do not edit its binding, state, quota ledger, lock, HEAD, or T30
evidence. A live `./dev status` before and after qualification must remain the same
T30 `HUMAN_GATE` with the same engine revision, HEAD, fingerprint, and dirty file
list.

## Compatibility lineage

Rolling compatibility was a completion gate before every implementation ticket, not
an activity deferred to T12. The following implementation commits are the retained
lineage; each is linked to the shared deterministic
[T30 no-model harness](../tests/test_t30_compatibility.py). The actual per-ticket
supervisor reports are host-local run evidence; preserve their recorded PASS reports
with this table through the approved cutover and rollback window.

| Plan position | Implementation commit | Compatibility evidence |
|---|---|---|
| T00 | `dc406b59e4afe7a65bdfe7ab1d36749e122deb99` | [fixture and harness](t30-compatibility-fixture.md) |
| T01 | `6e9c96ddbe9ca760960582b67f048f47059f239f` | [T30 harness](../tests/test_t30_compatibility.py) |
| T02 | `6de5e6e7413156c5f2cb7ff17bb0a28366d4f592` | [T30 harness](../tests/test_t30_compatibility.py) |
| T03 | `ad7f8c2f3ea50dc1da8fc09c9ca120999fc1cbab` | [T30 harness](../tests/test_t30_compatibility.py) |
| T04 | `f0a8fb8d3879926529ea4b1a77b9d57b30ac0f2c` | [T30 harness](../tests/test_t30_compatibility.py) |
| T05 | `bf25c4de8b5ac18bcac998f5ab50a262f2d30d73` | [T30 harness](../tests/test_t30_compatibility.py) |
| T06 | `66e08ef8df0558965693fc9660defd4a184f04df` | [T30 harness](../tests/test_t30_compatibility.py) |
| T07 | `42551c44caa64c0b76a91123391edcd43f3c1cff` | [T30 harness](../tests/test_t30_compatibility.py) |
| T08 | `98efdd93f64d23181bb99a781013f06500fdcb94` | [T30 harness](../tests/test_t30_compatibility.py) |
| F09 | `644f2d2c74df0e44702160c2bd877ee450608634` | [T30 harness](../tests/test_t30_compatibility.py) |
| T09 | `e7b838b1eb334b6253c42395eb6650bf4fc7fabe` | [T30 harness](../tests/test_t30_compatibility.py) |
| T10 | `29bddff9aabf3add7eb275c5b661dae7fbdc626e` | [T30 harness](../tests/test_t30_compatibility.py) |
| F10 | `a494c6b2ffbf45ec011a8af8f0bf656aa8d69edf` | [T30 harness](../tests/test_t30_compatibility.py) |
| F11 | `dd69fb89406016bf3bae81ef29c5bf9a0d6cc051` | [T30 harness](../tests/test_t30_compatibility.py) |
| T11 | `67be443e18003555e7ed3b1064d31bb62a9f00d0` | [T30 harness](../tests/test_t30_compatibility.py) |

## Preflight

Two operators participate: the cutover operator performs commands on an isolated
copy; the witness independently compares the evidence and records go/no-go. Neither
operator makes undocumented state edits. Before the rehearsal, both confirm:

1. the authoritative plan order ends `... T10 → F10 → F11 → T11 → T12 → T99`, and
   every row above has a retained passing run report;
2. the fixture checksum inventory and the focused qualification test pass;
3. the source copy is a separately created temporary product repository, not the live
   product, and both source and candidate engine checkouts are separate, clean,
   immutable Git revisions;
4. the source copy alone has the host-local writer lease for the candidate build;
5. the source reports exactly the supported T30 gate, and the captured source
   checksum from dry-run is recorded verbatim; and
6. the translation manifest and deterministic documentation check are fresh.

Run the deterministic preflight from this repository:

```bash
python3 -m unittest tests/test_t30_compatibility.py tests/test_t12_personal_assistant_qualification.py
python3 scripts/check_documentation.py
git status --short --branch
```

Expected evidence is two passing test modules, the explicit documentation result
`pairing, links, freshness only; no semantic-equivalence claim`, and no unexpected
repository changes. A checksum mismatch, test failure, stale translation digest,
missing lineage report, dirty engine checkout, missing lease, or a live-path input is
an abort condition.

## Isolated rehearsal

Create the temporary product and engine copies using the fixture test; do not replace
its generated placeholders with live values. The focused test performs this full
sequence and leaves no durable product outside its temporary directory:

```bash
python3 -m unittest -v tests/test_t12_personal_assistant_qualification.py
```

The witnessed manual sequence on that same type of isolated copy is:

```bash
./dev legacy-cutover dry-run --candidate <isolated-2.0-engine>
./dev legacy-cutover apply --candidate <isolated-2.0-engine> --source-checksum <dry-run-source_checksum> --go
./dev status
./dev resume
./dev stop
./dev legacy-cutover rollback
./dev status
```

Record the JSON dry-run receipt, `source_checksum`, candidate identity, archive path,
pre/post product HEAD and fingerprint, status output before/after each handoff, and
the stop acknowledgement. Expected results are: dry-run is `supported`; apply is
`cutover_applied`; the post-apply controller reports the migrated `HUMAN_GATE`; resume
does not start a model at that gate; stop reports an already-quiescent controller;
rollback is `rolled_back`; and the final status is the original v4 T30 gate.

The focused rehearsal also injects refusal paths for no explicit go, a changed source
checksum, an active source control record, and a mismatched dirty fingerprint. Each
must fail before an authority handoff and preserve the product snapshot. It checks
that the predecessor archive is retained, legacy consumed quota authorization becomes
invalidated rather than reusable, and a second controller cannot proceed without the
candidate lease. Existing deterministic lifecycle coverage exercises a stopped/
re-entered first controlled-ticket checkpoint and an interrupted commit reconciliation
without a second invocation or commit; retain that test output with the T12 record.

Abort immediately if a product HEAD/fingerprint changes outside the intentional first
controlled-ticket fixture, an invocation or commit identity is duplicated, a consumed
quota authorization is accepted again, two controllers/locks are observed, status is
not read-only at the gate, the source checksum changes, or any required receipt is
missing. Preserve the isolated copy and evidence; do not repair JSON, binding, quota,
archive, state, or lock files by hand.

## Recovery and final gate package

For an abort before apply, retain the dry-run receipt and destroy no evidence: the
legacy binding remains active. For an abort after apply, first stop the candidate
controller at a quiescent checkpoint, then run `./dev legacy-cutover rollback` from
the isolated copy. Verify the restored predecessor archive checksum, source binding,
v4 state, quota ledger, HEAD, fingerprint, and sole legacy lock authority. Re-entry
starts with `./dev status`; it never starts a model merely by inspecting or resuming a
closed `HUMAN_GATE`.

The final human package must link this runbook, the fixture/checksums, the complete
compatibility lineage above, dry-run/apply/rollback receipts, focused test output,
live before/after read-only status captures, and the documentation review below. The
owner alone decides whether to release the post-T12 gate. Do not run T99 under the
legacy controller; see [the T99 sentinel](architecture/tickets/99-cutover-sentinel.md).

The witness also records that [documentation governance](documentation-governance.md)
classifies legacy material, that the maintained pair is present in
[`translation-manifest.json`](translation-manifest.json), and that migration,
rollback, compatibility, and cutover evidence remains linked through the rollback
window. The check validates pairing, links, and freshness only; it does not claim
semantic translation equivalence.
