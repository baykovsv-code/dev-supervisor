# F10: Documentation governance and operator reconciliation

## Objective

Establish the minimum documentation governance needed before legacy cutover and
reconcile the implemented T01-T10 behavior into current operator documentation.

## Prerequisites

- T00-T10, including F09, are complete.
- English remains the complete normative documentation set.

## Scope

- Define the maintained Russian operator subset covering introduction, core behavior,
  safety rules, commands/workflows, limitations, quota, gates,
  commit/push/self-modification, and recovery.
- Add a lightweight translation manifest that declares unique maintained
  English/Russian path pairs and records the reviewed normative-English content digest
  as the deterministic freshness basis.
- Add deterministic checks for declared pairs, valid links, and staleness. State
  explicitly that these checks do not prove semantic equivalence and that English
  remains normative.
- Require an explicit `Documentation impact` classification on pending and future
  tickets. Behavior-changing tickets must update affected normative English operator
  material and every affected maintained Russian operator document in the same ticket.
- Reconcile implemented T01-T10 behavior into current operator material, including
  configuration/capabilities, lifecycle and plan epochs, state/events, project
  admission, backlog intake, quota, controlled improvement/self-development,
  deterministic-verification recovery, push persistence, and immutable engine update.
- Inventory legacy documentation as current, transitional, archived, or obsolete.
  Preserve discoverable migration, rollback, compatibility, and cutover evidence
  through the approved cutover and rollback window regardless of classification.
- Add documentation acceptance to T11 and T12 and a final pre-cutover documentation
  gate.

- Files/modules: `docs/`, `scripts/` (documentation consistency check), and focused
  documentation tests under `tests/`.

## Acceptance criteria

- English documentation is identified as the sole complete normative set; the
  maintained Russian operator subset covers every topic listed in scope.
- The manifest rejects duplicate/missing pairs and a changed English digest until its
  paired translation is reviewed and the manifest is deliberately refreshed; link and
  staleness checks pass and make no semantic equivalence claim.
- Operator documentation accurately reflects implemented T01-T10 behavior and the
  compatibility harness still passes without product or runtime-state mutation.
- Every pending ticket has an explicit documentation-impact classification, and the
  ticket contract requires that classification for future tickets.
- Every legacy document has exactly one lifecycle classification, while required
  migration, rollback, compatibility, and cutover material remains visible and linked.
- T11, T12, and the post-T12 human gate contain explicit documentation acceptance.

## Documentation impact

`Required — governance baseline and operator reconciliation.` This ticket owns the
initial manifest, classifications, maintained subset, and T01-T10 documentation
reconciliation.

## Non-goals

- making Russian documentation normative or complete beyond the maintained subset;
- asserting machine-checked semantic translation equivalence;
- deleting or hiding legacy migration, rollback, compatibility, or cutover evidence;
- implementing T11 cutover behavior.
