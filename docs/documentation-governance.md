# Documentation governance

English is the sole complete normative documentation set for Supervisor 2.0. Russian
operator documents in the maintained subset are operational translations, not an
independent authority. Where text differs or is incomplete, English controls.

## Maintained Russian operator subset

The bounded subset is [the Russian operator guide](operator-guide.ru.md), paired with
the normative [English operator guide](operator-guide.md). Together with their linked
normative English references, it covers introduction, core behavior, safety rules,
commands and workflows, limitations, quota, gates, commit/push/self-modification, and
recovery. It intentionally is not a complete translation of every English document.

`translation-manifest.json` declares this unique pair and records the SHA-256 digest
of the English content that a translator reviewed. After a normative English change,
the check fails until the paired Russian document is reviewed and the manifest digest
is deliberately refreshed in the same reviewed change.

Run the deterministic check from the repository root:

```bash
python3 scripts/check_documentation.py
```

It verifies declared-pair uniqueness and existence, local links in the manifest and
maintained pair, and English-digest freshness. It does **not** establish translation
quality or semantic equivalence, and it never makes Russian text normative.

## Ticket documentation impact

Every pending and future implementation ticket must contain a `## Documentation
impact` section. `None` is an explicit reviewed classification. A behavior-changing
ticket must update affected normative English operator material and every affected
maintained Russian operator document in that same ticket, then refresh the manifest
only after translation review. The implementation plan carries the same delivery rule.

## Legacy-document inventory

This inventory covers the legacy source material transferred in the extraction
analysis. Each listed document has exactly one lifecycle classification; classification
does not authorize deletion.

| Legacy document | Classification | Retention / current route |
|---|---|---|
| [architecture-as-is.ru.md](architecture-as-is.ru.md) | archived | Historical 1.x architecture; retain through cutover/rollback. |
| [state-machine.ru.md](state-machine.ru.md) | archived | Historical 1.x state evidence; retain through cutover/rollback. |
| [principles.ru.md](principles.ru.md) | archived | Historical 1.x principles; retain through cutover/rollback. |
| [limitations.ru.md](limitations.ru.md) | archived | Historical limits and migration rationale; retain through cutover/rollback. |
| [quickstart.ru.md](quickstart.ru.md) | obsolete | Do not use as a 2.0 runbook; preserve as 1.x evidence through cutover/rollback. |
| [backlog/supervisor-as-is-and-usage-ru.md](backlog/supervisor-as-is-and-usage-ru.md) | archived | Historical assessment index; retain through cutover/rollback. |

Current operator material is [operator-guide.md](operator-guide.md) and its maintained
Russian pair. [migration-analysis.md](architecture/migration-analysis.md) is
transitional evidence. Migration, rollback, compatibility, and cutover evidence stays
discoverable through the approved cutover and rollback window via the migration
analysis, [T30 fixture](t30-compatibility-fixture.md), [T11](architecture/tickets/11-legacy-cutover.md),
[T12](architecture/tickets/12-personal-assistant-qualification.md), and
[T99](architecture/tickets/99-cutover-sentinel.md), regardless of classification.
