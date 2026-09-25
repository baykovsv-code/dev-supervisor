# Documentation governance

English is the complete normative documentation set. The Russian guide is a reviewed
operational counterpart, not an independent authority. If the texts differ, English
controls.

## Maintained pair and review

The sole maintained pair is [the English operator guide](operator-guide.md) and
[the Russian operator guide](operator-guide.ru.md). It covers installation, the mental
model, ordinary operation, quota, gates, safe stops, recovery, authority, commits,
push, migration, rollback, and platform limits.

`translation-manifest.json` records that unique pair and the SHA-256 digest of the
English text reviewed with its Russian counterpart. Refresh the digest only after
reviewing every maintained Russian section against the final English source. The
manifest and its deterministic check establish pair uniqueness, local-link resolution,
and source freshness only. They do not assess translation quality or assert semantic
equivalence.

Run from the repository root:

```bash
python3 scripts/check_documentation.py
```

## Documentation impact

Every implementation ticket declares `## Documentation impact`. `None` is an explicit
reviewed classification. A behavior change updates affected normative English material
and the maintained Russian guide in the same ticket, then refreshes the manifest after
translation review.

## Historical inventory and retention

The following 1.x narratives and completed 2.0 specifications are historical, not
current operating instructions. Their current-tree copies may be removed only after
the operator guide preserves every still-supported invariant and route below. Removal
does not rewrite Git history or delete ignored runtime archives, engine checkouts,
receipts, bindings, or run evidence.

| Material | Classification | Preserved current route |
|---|---|---|
| 1.x architecture, state-machine, principles, limitations, quickstart, migration, and assessment narratives | archived history at `v2.0.0` | Operator guide: mental model, gates, safe stops, recovery, migration, and rollback. |
| Completed 2.0 architecture, requirements, plan, tickets, compatibility fixture, and cutover runbooks | archived history at `v2.0.0` | Operator guide: authority, single writer, lifecycle, recovery, migration, engine update, rollback, commits, and push. |
| Current 2.1 backlog and deferred platform qualification | current | [BACKLOG.md](../BACKLOG.md) and [2.1 candidate](backlog/supervisor-2.1.md). |

Use Git history to inspect historical evidence; it is not a live recovery dependency.
Live recovery begins with `./dev status` and follows the current operator guide and
the active policy/ticket. A recovery command must never point only to a removed
historical document.

## Approved 2.1 neutralization boundary

The completed 2.0 baseline is the exact commit tagged `v2.0.0`. Its obsolete tracked
1.x and 2.0 architecture, cutover, qualification, and fixture material is retired
from this working tree only after the current operator guide preserves every
still-supported invariant and recovery route. Git history is not rewritten. Ignored
runtime archives, engine checkouts, bindings, receipts, and run evidence remain
untouched.

To make the T20 commit a genuinely neutral predecessor, the identity-coupled
compatibility fixture and its direct tests and documentation are historical material
as well. T22 owns the replacement generic compatibility expansion, bounded
self-hosted acceptance loop, and its fault matrix. The active materialized 2.1 plan
remains immutable while this boundary is applied.
