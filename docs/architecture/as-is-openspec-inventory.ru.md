# Инвентаризация Supervisor AS-IS и сравнение с OpenSpec

Дата оценки: 2026-11-18. Исследованный коммит:
`07bb23209aa5141fd1d2b606c06c852bdc2b8e7f` (чистая ветка `main` до подготовки отчёта).
[Английская версия](as-is-openspec-inventory.md).

**Вывод:** Supervisor совмещает систему планирования и локальный контроллер
исполнения. OpenSpec может взять на себя значительную часть первой роли;
исследованные интерфейсы OpenSpec не заменяют вторую. Если оставить оба комплекта
планов независимыми источниками истины, дублирование сохранится и появится риск
расхождения данных.

Это оценка и предлагаемая модель работы, а не утверждённая поведенческая
спецификация. По просьбе пользователя работа останавливается после групп задач 1–4:
пошаговая дорожная карта миграции, график удаления и checklist её согласования
(группа 5) здесь отсутствуют. Итоговая проверка полного изменения 6.1 остаётся
открытой. Поведение контроллера, политики, схем, runtime и управляемых проектов
не меняется.

## 1. Исходная точка и правила доказательности

Для установленного поведения приоритет имеют отслеживаемые код и тесты; для
операторского контракта — актуальное английское руководство. Исторические
архитектурные документы и обсуждение подтверждают намерения. Наличие теста
показывает покрытие сценария, но не доказывает прохождение этого сценария в живой
эксплуатации. Рекомендации ниже относятся к будущему и не дают разрешения на действия.

[Манифест структурных свидетельств](as-is-openspec-evidence.json) содержит пути
отслеживаемых файлов, SHA-256, число строк, обязательные поля схем, имена тестов,
узлы CLI-парсера и литеральные константы состояний на исследованном коммите.
Сгенерированные workflows из `.agents/skills/` рассмотрены отдельно. Измерения
воспроизводятся через `git ls-files`, Python `ast.parse` для `supervisor.py` и
`tests/test_*.py`, а также `len(Path(path).read_text().splitlines())`.
Строки считаются вместе с пустыми; узлы парсера — вызовы `add_parser`, а не
число допустимых сочетаний команд.

Игнорируемая `.dev-supervisor/`, данные аккаунта, журналы запусков, внешние
управляемые репозитории и секреты не исследовались и не копировались. Отслеживаемая
проектная политика рассмотрена структурно; её частные и контекстные значения
не воспроизводятся. Поэтому из этой оценки нельзя установить реальную частоту
запусков, расход квоты, частоту эксплуатационных сбоев, квалификацию хостов и факт
завершения релиза.

Установленный CLI: `openspec --version` → **1.14.3**. Workflow пакета:
`spec-driven`, версия схемы **1** (`openspec schema which spec-driven --json`,
затем чтение найденного `schema.yaml`). Сгенерированные skills декларируют
`generatedBy: 1.14.3`; исследовано и их содержимое. `openspec list --json`
выбирает этот репозиторий как `nearest`; в [конфигурации](../../openspec/config.yaml)
store не объявлен. Основных спек нет; активно одно изменение; архив содержит только
`.gitkeep`. Готовность артефактов планирования в `status` отличается от выполнения
задач в `instructions apply`.

Официальные материалы соответствующей версии:
[описание workflow](https://github.com/Fission-AI/OpenSpec/blob/v1.14.3/docs/workflows.md)
и [справочник CLI](https://github.com/Fission-AI/OpenSpec/blob/v1.14.3/docs/cli.md).
Они описывают действия ассистента и поддержку CLI; подробные свидетельства для этой
установки — результаты локальных команд, установленная схема и skills.

## 2. Компоненты и их ответственность

C1–C12 — единицы покрытия для матрицы ответственности. Манифест перечисляет
отдельные отслеживаемые файлы этих групп, включая схемы и тесты. Объединение
в группу не означает одинакового решения о сохранении всех её элементов.

| Группа | Компоненты и назначение | Свидетельства в коде и документах |
|---|---|---|
| C1 | `supervisor`, `dev`, инициализация: вход в engine, launcher с привязкой, создание control-файлов и начальных документов | [Контроллер](../../supervisor.py): `initialize_repository`, `project_launcher_text`; [launcher](../../dev); [точка входа](../../supervisor) |
| C2 | Политика и полномочия: проверка проектных ограничений, пересечение с разрешениями хоста, вывод безопасной конфигурации | `validate_project_policy`, `load_host_capability_grants`, `Supervisor.__init__`, `effective_configuration`; [политика](../../dev-supervisor.json); [тесты](../../tests/test_policy_contract.py) |
| C3 | Планирование: cold start, admission, циклы бэклога, неизменяемые epochs, вставка prerequisites, явные улучшения | `AdmissionReview`, `begin_cold_start`, `materialize_cold_start_plan`, `materialize_backlog_epoch`, `apply_insertion_plan_amendment`, `materialize_improvement_plan`; [тесты улучшений](../../tests/test_controlled_improvement.py) |
| C4 | Координация исполнения: состояние, блокировки одного писателя, run/resume/stop, dashboard и время | `operation_lock`, `initial_state`, `load_state`, `transition`, `_run_loop`, `resume`, `request_stop`, `dashboard`; [основные тесты](../../tests/test_supervisor.py) |
| C5 | Квота: ручные наблюдения, проверки по ролям, TTL/повторное использование, долговечная авторизация, преобразование ledger | `QuotaProvider`, `ManualQuotaProvider`, `_guard_quota`; [тесты квоты](../../tests/test_observed_quota_policy.py) |
| C6 | Запуск моделей и отчёты: CLI runner, watchdog, структурированные результаты, диагностика и ограниченное исправление engine | `CodexRunner`, `run_process_with_watchdog`, `validate_report`, `_invoke`, `_invoke_diagnostic`, `_invoke_supervisor_repair` |
| C7 | Проверки, scope, транзакции Git и восстановление по checkpoint | `_run_verification`, `_scope_gate`, `_prepare_commit`, `_finish_commit`, `_reconcile_push`, `recover_generic_verification_failure`, `recover_protected_snapshot` |
| C8 | Идентичность engine, владение хостом, обновления и преобразование legacy/state | `_assert_engine_binding`, `_assert_writer_lease`, `activate_engine_update`, `apply_state_migration`, `apply_legacy_cutover`, `apply_later_scope_recovery` |
| C9 | 19 схем: отчёты; approval/admission/cold-start/backlog/improvement/epoch; audit; политика; разрешения/владелец хоста; identity/binding engine; версии состояния | [Манифест схем](as-is-openspec-evidence.json); примеры: [политика](../../schemas/project-policy-v2.schema.json), [состояние](../../schemas/supervisor-state-v7.schema.json) |
| C10 | Восемь промптов: `implement`, `architecture-blocker`, `diagnose`, `supervisor-repair`, `cold-start-review`, `existing-project-admission`, `backlog-cycle-review`, `improvement-review` | [Реализация](../../prompts/implement.md), [архитектура](../../prompts/architecture-blocker.md), [диагностика](../../prompts/diagnose.md); все перечислены в манифесте |
| C11 | Пять модулей тестов, policy/quota fixtures для cutover и reference-policy, скрипт проверки документации | [Основные](../../tests/test_supervisor.py), [политика](../../tests/test_policy_contract.py), [квота](../../tests/test_observed_quota_policy.py), [улучшения](../../tests/test_controlled_improvement.py), [документация](../../tests/test_documentation_governance.py), [скрипт](../../scripts/check_documentation.py) |
| C12 | Актуальный операторский контракт и бэклог; исторические требования, архитектура, план, тикеты и анализ миграции; OpenSpec и его workflows | [Руководство](../operator-guide.md), [governance](../documentation-governance.md), [бэклог 2.1](../backlog/supervisor-2.1.md), [исторические требования](requirements-index.md), [план](implementation-plan.md), [анализ миграции](migration-analysis.md), [proposal](../../openspec/changes/inventory-as-is-for-openspec-evolution/proposal.md) |

Особенности схем: `project-policy-v2.schema.json` фактически объявляет **v3**;
рядом с runtime v7 остаются схемы v5/v6, рядом с host grants v2 — v1.
Имя файла не является надёжным свидетельством версии. Схемы не заменяют все проверки:
`validate_project_policy`, валидаторы отчётов, state/epoch/checkpoint содержат
дополнительную семантику. Часть схем допускает произвольные объекты или строку phase;
соответствие JSON-схеме само по себе не доказывает безопасность перехода.

## 3. Жизненный цикл, хранение и решения AS-IS

Обычный путь (`_run_loop`, `_process_invocation`, `_finish_commit`):

```text
READY → проверка и списание разрешения квоты → IMPLEMENTING → проверка отчёта
  pass → VERIFYING → SCOPE_PENDING → COMMITTING → [PUSHING] → следующий READY
                                                          → PLAN_COMPLETED
  неоднозначность/отклонение → ARCHITECTURE_PENDING → ARCHITECTURE_REVIEW
  продуктовое решение → HUMAN_GATE
  восстановимое прерывание/блок → явное восстановление → RECOVER_MODEL
  повторные попытки implementation → DIAGNOSTIC_PENDING → DIAGNOSTIC_REVIEW
    → исправление продукта / host verification / архитектура / человек / ремонт engine
```

Архитектурный результат проходит детерминированные проверки и scope. Он не выдаёт
полномочия и не заменяет решение владельца продукта. Блокер после правок продукта
может сначала привести к `GIT_BLOCKED`; для protected-scope review существует
отдельный путь сохранённого checkpoint. `resume` для `PLAN_COMPLETED` ничего не
исполняет и не придумывает следующий тикет.

### Покрытие CLI

Ниже представлены все **25** команд верхнего уровня. Подкоманды и строки исходника
перечислены в манифесте: всего 71 узел парсера.

| Семейство | Команды и назначение |
|---|---|
| Создание/наблюдение | `init`, `status`: начальные файлы и чтение состояния |
| Исполнение | `run`, `resume`, `stop`: продвижение, сверка checkpoint, кооперативная остановка |
| Планирование | `admission` (assess/begin/status/approve/index), `cold-start` (begin/status/submit/correct/approve-requirements/approve-architecture/plan), `backlog` (begin/status/submit/approve-requirements/approve-architecture/materialize), `improvement` (request/status/submit-architecture/approve-architecture/materialize-plan/stage-successor) |
| Человеческие решения | `gate` (release/accept-cutover/reconcile-plan/adopt-architecture) |
| Квота/свидетельства | `quota` (show/set/migration-dry-run/migration-apply/migration-rollback), `evidence check` |
| Исправление/сверка | `recover-environment`, `recover-verification-failure`, `recover-generic-verification-failure`, `recover-protected-snapshot`, `reconcile-verification-evidence` |
| Совместимость/передача управления | `policy-migration-dry-run`, `state-migration-dry-run`, `state-migration-apply`, `state-migration-rollback`, `engine-update` (dry-run/activate/rollback), `scope-recovery` (dry-run/apply/rollback), `plan-amendment` (dry-run/apply/rollback), `legacy-cutover` (dry-run/apply/rollback) |

### Семейства сохраняемого состояния

Это контракты хранения, установленные по конструкторам и местам записи, а не копии
живых файлов. Все пути ниже относительно игнорируемой `.dev-supervisor/`.

| Хранилище | Назначение и код |
|---|---|
| `state.json` | phase/ticket, завершённые тикеты, active run, blockers/resolution, recovery context, epochs, pending commit/push, gate, счётчики, history/audit; `initial_state`, `load_state`, `transition`, `_finish_commit` |
| `cold-start.json`, `cold-start/` | Исходная спецификация, неизменяемые ревизии требований/архитектуры, точные approvals, готовность плана; `_load_cold_start` |
| `admission.json` | Digests исходников/manifest, approval и provenance index; `AdmissionReview` |
| `backlog-cycle.json`, `backlog-cycles/` | Выбор работ, ревизии/approvals, материализованные документы epoch; `_load_backlog_cycle` |
| `improvement.json`, `improvements/` | Явный запрос, impact review, ограниченный план, эскалация/квитанция successor; `_load_improvement` |
| `quota.json`, `quota-predecessors/` | Идентичность наблюдений, авторизации, инвалидирование, rollback преобразования; `ManualQuotaProvider` |
| `engine.json`, `host-owner.json`, `host-capabilities.json` | Неизменяемая привязка, lease писателя, полномочия хоста и push; конструктор и валидаторы |
| `engine-update.json`, `engine-archives/`, `scope-recovery.json` | Квалифицированная передача управления и точные rollback-свидетельства; методы engine update/scope recovery |
| `plan-amendment.json`, `legacy-cutover.json`, `legacy-cutover-archives/`, `state-predecessors/` | Квитанции append-only изменения плана/преобразований и восстановление предшественника; amendment/state/cutover |
| `runs/` | Промпт, команда, invocation/outcome, usage, отчёт, изменённые файлы/diff, журналы/checks, диагностические сведения; `CodexRunner`, `_invoke*`, `_run_verification` |
| `timing-history.json`, `stop-request.json`, lock-файлы | Наблюдения времени, кооперативное прерывание и исключение второго писателя; `_record_timing`, `request_stop`, `operation_lock` |

В основном runtime объявлены 17 терминальных состояний; список есть в манифесте.
Активные состояния охватывают реализацию, архитектуру, проверки, scope, commit/push,
диагностику и ремонт. Вспомогательные автоматы объявляют три cold-start phase,
четыре backlog phase и пять improvement phase. Admission использует сценарии A/B
и статусы совместимости. Литеральные вызовы `transition` называют 26 разных целевых
состояний — это нижняя оценка: часть передаётся переменными (`IMPLEMENTING`,
`ARCHITECTURE_REVIEW`, состояния квоты и восстановления). Это не размер полного
графа состояний и не число достижимых комбинаций.

### Вызовы моделей и детерминированная работа

Места запуска три: `_invoke` для implementation/architecture,
`_invoke_diagnostic` для классификации, `_invoke_supervisor_repair` для ремонта
engine. В каждом авторизация квоты расходуется до запуска модели. Review-промпты
cold-start/admission/backlog/improvement задают подготовку предложений внешним
ассистентом; их CLI submission/approval/materialization выполняются детерминированно
и не являются дополнительными автоматическими вызовами моделей.

Разбор отчёта, fingerprints, проверка состояния/квоты, verification-команды,
Git reconciliation, status, операции gate и проверки архивов/преобразований — работа
контроллера. Verification-команды могут запускать любые настроенные программы;
детерминированность перехода не доказывает чистоту, ограниченность и отсутствие
вызовов моделей у каждой такой программы.

Участие человека требуется шире, чем при продуктовой неоднозначности: cold-start
и backlog требуют точного одобрения требований/архитектуры; admission — исходников;
improvement — явного триггера, capability и impact approval. Есть milestone/evidence/
periodic gates и отдельные маршруты передачи engine. `release_gate` требует
непустую заметку и повторно сверяет evidence/fingerprint/plan по типу gate.
Для продуктового решения нужен новый human-authored commit. Код проверяет смену
HEAD; человеческое авторство остаётся операторским контрактом без независимой
аутентификации.

## 4. Контроли и инварианты

В таблице — реализованные проверки в пределах их предусловий, а не безусловные
гарантии. Имена тестов — ссылки на покрытие в отслеживаемом наборе.

| Контроль / предотвращаемая ошибка | Код / тест | Стоимость и участие человека |
|---|---|---|
| Неизвестная/устаревшая квота не разрешает запуск; один invocation не расходует разрешение дважды | `ManualQuotaProvider.evaluate/consume/invalidate`, `_guard_quota`; quota `test_consumption_is_idempotent_and_legacy_conversion_rolls_back` | Детерминированно; medium — один вызов, high — TTL/число использований; обновление пока ручное |
| Зависшая модель и оставшиеся дочерние процессы | `run_process_with_watchdog`, `_terminate_process_group`; main `test_watchdog_timeout_leaves_no_child_process` | Таймер/процессы; предупреждение/завершение; явное восстановление может стоить ещё одного вызова |
| Устаревшие HEAD/tree/run нельзя продолжить как прежний checkpoint | `_model_checkpoint_matches`, `_ensure_recovery_git`; `test_stale_protected_scope_checkpoint_fails_closed_without_quota_or_model` | Hash/Git; несовпадение разрешает оператор |
| PASS модели не заменяет verification | `_run_verification`, `_verification_output_errors`; `test_failed_verification_prevents_commit`, `test_skipped_host_verification_fails_closed` | Настроенные проверки и журналы; без вызова модели контроллером |
| Protected/later-owned scope нельзя расширять молча | `_scope_gate`, `_preserved_paths_match`; `test_preserved_architecture_entry_blocks_modified_product_without_consuming_quota` | Сначала детерминированно; protected review может вызвать архитектурную модель; исключения требуют точных свидетельств |
| Commit/restart не должен дублировать транзакцию продукта | `_prepare_commit`, `_finish_commit`; `test_resume_reconciles_commit_without_duplicate_invocation_or_commit` | Git и долговечные checkpoints; неоднозначная история останавливает процесс |
| Политика репозитория не может перенаправить push | `_verified_push_target`, `_reconcile_push`; policy `test_verified_push_target_requires_exact_branch_and_remote_urls` | Отдельное разрешение хоста, точные remote/branch/commit; перед повтором сверяется remote |
| Модель/репозиторий не повышают полномочия | `Supervisor.__init__`, `require_capability`; policy `test_capabilities_are_independent_and_intersect_host_and_repository` | Пересечение grants, детерминированный отказ |
| Audit и связь с предшественником обнаруживают противоречивые recovery-свидетельства | `audit_event`, `_validate_state_v7`, `_append_audit_event`, `recover_generic_verification_failure`; `test_generic_verification_recovery_audits_once_without_quota_model_or_check` | Локальная цепочка checksum; не внешний защищённый или подписанный audit log |
| Неизменившийся generic verification failure не должен автоматически повторять проверки | `_generic_verification_failure_checkpoint`, `recover_generic_verification_failure`; `test_generic_verification_failure_resume_is_inert_until_explicit_recovery` | Явное открытие repair без модели проверяет один failed configured ticket check и журнал; затем обычный ремонт и полный цикл проверок |
| Преобразование/rollback сохраняют предшественника | `apply_state_migration`, `apply_legacy_cutover`; `test_qualified_cutover_is_opt_in_archives_exact_predecessor_and_rolls_back` | Dry-run, архив с checksum, явное go; ограничения конкретного перехода |
| Передача engine исключает старый хост/писателя | `_assert_engine_binding`, `_assert_writer_lease`, `activate_engine_update`; `test_immutable_binding_requires_host_local_lease_and_stale_host_cannot_write` | Квалификация identity/совместимости, активация в покое, rollback |

Ограничения: watchdog относится к процессам моделей, а не задаёт универсальный
deadline всем verification subprocess. Unit tests не доказывают распределённую
блокировку или координацию между хостами. Исследованные механизмы локальны хосту.

## 5. Исторические намерения и текущий код

Источники: [сентябрьский документ](../dev-supervisor-discussion-2026-09-25.md),
[текущий бэклог](../../BACKLOG.md), [кандидат 2.1](../backlog/supervisor-2.1.md),
[отложенная квалификация macOS](../backlog/macos-platform-qualification-2.1.md).

| Идея | Статус на исследованном коммите | Свидетельства / ограничения |
|---|---|---|
| Завершение/cutover 2.0; закрытие T99 без модели и фиктивного commit | Релизное утверждение историческое; точный механизм reconciliation реализован | `accept_legacy_cutover`, `LegacyCutoverTests`; живой cutover не исследован |
| Новая работа — новый epoch, без ретроактивных правок 2.0 | Контракт реализован, остаётся актуальным | `_complete_plan_epoch`, `materialize_backlog_epoch`, `BacklogCycleTests` |
| Автоматический краткоживущий Codex app-server quota reader, buckets по длительности, identity provider и manual fallback | Актуальный замысел; автоматический provider текущим кодом не поддержан | Конструктор принимает только `manual`; `rg -n 'app-server|rateLimits' supervisor.py tests/` ничего не находит; ручные TTL/reuse/account/model context реализованы |
| Понятные EN/RU guides и freshness-only manifest | Структура реализована; понятность требует редакционной оценки | Guides, `check_documentation.py`, тесты документации; семантическая эквивалентность не доказана |
| Удаление старых 2.0 narrative/tickets после сохранения гарантий | Частично реализованное намерение; исторические файлы остаются | Governance задаёт границу удаления, но `docs/architecture/` ещё содержит файлы; завершение очистки T20 не установлено |
| Публичная нейтральность и project-independent compatibility | В текущем дереве не завершено; нейтральность утверждать нельзя | Generic fixtures соседствуют с legacy-specific именами/допущениями в старых документах и тестах; частные значения здесь не копируются |
| Компактная fixture и ограниченная self-hosted fault matrix на точном T20 | Актуально; отдельные fault tests реализованы, полный acceptance не подтверждён | Три fixture JSON и fake runners; отслеживаемого T22 acceptance artifact с полной матрицей/predecessor не установлено |
| Один настоящий ограниченный Codex acceptance receipt перед релизом | Намерение квалификации не подтверждено | Отслеживаемые источники не устанавливают наличие T24 receipt; unit tests его не заменяют |
| Linux baseline; macOS только review/simulation, затем отдельная inbound-only квалификация | Актуальная документированная граница; фактическая квалификация не перепроверялась | Operator guide и deferred candidate; реальную поддержку Mac выводить нельзя |
| Сохранение Git history и ignored recovery evidence; отсутствие forecast | Актуально; no-forecast подтверждается кодом/тестами | Архивы миграции и `test_dashboard_has_no_quota_forecast`, `test_timing_history_does_not_create_a_quota_forecast` |
| Порядок T20 → T21 → T22 → T23 → T24 | Исторический/текущий план бэклога, не свидетельство исполнения | Порядок назван в бэклоге; инвентаризация не позволяет отметить его завершённым |

Сентябрьский файл сам является обновлением после 2.0, а не дословным старым
разговором. Зафиксированные намерения не доказывают реализацию и не разрешают
новую работу по миграции.

## 6. Структурная сложность и затраты квоты

Измерено: **10 184** строки и **291** определение функций в `supervisor.py`;
**19** схем (**533** строки), **8** промптов (**172** строки), **5** тестовых модулей
(**5 429** строк, **205** методов `test_`). Основной тестовый файл — **5 026** строк.
CLI — **25** команд верхнего уровня, **71** узел парсера; состояния описаны в разделе 3.
Это размер поверхности исходников, а не оценка сопровождаемости или runtime-затрат.

Статическая оценка пути: успешная обычная реализация требует одного вызова модели,
затем verification/scope/commit. Архитектурный блокер добавляет как минимум один
архитектурный вызов и, возможно, новый implementation. Повторное восстановление
implementation после порога добавляет diagnostic (`_maybe_trigger_diagnostic`,
минимальный порог — два), затем возможны repair и повторная классификация.
Освобождение human-evidence gate может потребовать model review того же тикета
(`release_gate`). Единого числа вызовов для всех тикетов или гарантированного
процента экономии от OpenSpec здесь не установлено.

Кандидаты на снижение дублирования/затрат: три процесса revision/approval/
materialization (cold-start, backlog, improvement), отдельные plan parsing/epoch/
amendment, повторное чтение authoritative documents в промптах, diagnostic/repair
reclassification, периодические человеческие checkpoints. Часть повторов защищает
полномочия и восстановление: одно уменьшение числа файлов не оправдывает удаление gate.

Неизменившийся generic verification failure явно инертен. Прерванную verification
можно продолжить без повторения завершённой модели; успешные checks сохраняются.
Однако восстановление прерванной модели может расходовать новый вызов при том же
дереве продукта; diagnostic threshold сам по себе не задаёт общий бюджет попыток и
стоимости. Принцип отсутствия неизменившихся повторов сильнее того, что доказуемо
одной ограниченной эскалацией в исходниках.
Фактические токены, частота reviews, время, частота одинаковых повторов и экономия
**неизвестны**: runtime-журналы не читались.

## 7. Возможности OpenSpec по установленной версии 1.14.3

| Возможность | Воспроизводимый источник/команда | Граница и сравнение |
|---|---|---|
| Граф зависимостей артефактов | `openspec schemas --json`; `openspec schema which spec-driven --json`; найденный `schema.yaml`; `status --change inventory-as-is-for-openspec-evolution --json` | Proposal предшествует specs и design; tasks требуют specs и design; apply — tasks. Здесь specs явно пропущены. Наличие файлов не доказывает runtime acceptance |
| Требования и документы изменения | `openspec instructions proposal --change inventory-as-is-for-openspec-evolution --json`; установленная схема | Proposal, capability delta requirements/scenarios, design и tasks могут владеть содержимым планирования, которое сейчас хранит Supervisor |
| Контекст и прогресс apply | `openspec instructions apply --change inventory-as-is-for-openspec-evolution --json`; tracked apply skill | CLI возвращает пути и состояние задач, ассистент реализует и отмечает checkbox. Scheduler, quota ledger и watchdog моделей здесь не обнаружены |
| Ревизия плана | Tracked `openspec-update-change/SKILL.md` | Согласованно меняет planning artifacts без правок кода; не предоставляет exact-digest operator authorization Supervisor |
| Validation | `openspec validate --help`; strict validation текущего change | Проверяет artifacts/specs; не запускает продуктовые тесты и не доказывает acceptance. Валидное изменение может содержать незавершённые задачи |
| Sync | Tracked `openspec-sync-specs/SKILL.md` | Ассистент переносит ADDED/MODIFIED/REMOVED/RENAMED requirements в основные спеки; это не commit проверенной продуктовой транзакции |
| Archive | `openspec archive --help`; tracked archive skill | CLI archive умеет обновлять спеки; skill может предварительно sync и переместить change. `--skip-specs`/metadata поддерживают документационные изменения. Runtime predecessor archives этим не заменяются |
| Stores и выбор корня | `openspec store --help`, `list --json`; правила generated skills | Отдельные зарегистрированные spec repositories выбираются через `--store`; здесь не используются. Это не writer lease, распределённое исполнение и не remote persistence продукта |

Исследованные workflows: [apply](../../.agents/skills/openspec-apply-change/SKILL.md),
[update](../../.agents/skills/openspec-update-change/SKILL.md),
[sync](../../.agents/skills/openspec-sync-specs/SKILL.md),
[archive](../../.agents/skills/openspec-archive-change/SKILL.md),
[propose](../../.agents/skills/openspec-propose/SKILL.md),
[explore](../../.agents/skills/openspec-explore/SKILL.md).

Выводы об отсутствии относятся к исследованным интерфейсам/workflows и не утверждают,
что внешняя интеграция OpenSpec принципиально не может добавить runtime-сервисы.

## 8. Матрица пересечений и ответственности

S — Supervisor, O — OpenSpec, H — оператор. Будущие владельцы — только рекомендация.
Уверенность H/M: прямое свидетельство / проектный вывод, требующий интеграционного
эксперимента. Зависимости — условия, а не упорядоченный план миграции.
Классы: retain — сохранить; delegate to OpenSpec — передать; integrate — связать;
simplify — упростить; retire — вывести из употребления; unresolved — решение открыто.

| Группа / функция | Сейчас → предложение; класс | Свидетельство | Последствие для безопасности / условие | Уверенность |
|---|---|---|---|---|
| C1 launcher/init | S → S; retain | `initialize_repository`, `dev` | Сохранить immutable binding; scaffold должен учитывать выбранного владельца планирования | H |
| C2 configuration/grants | S/H → S/H; retain | Проверка политики и тесты | Контент OpenSpec не выдаёт push/mutation/quota authority | H |
| C3 требования, design, tickets | S → O; delegate to OpenSpec | Cold-start/backlog против proposal/spec/design/tasks | Прекратить параллельную власть над контентом можно после привязки task/change identity и содержимого | M |
| C3 admission mapping | S/H → O контент + S проверка входов; integrate | `AdmissionReview`, apply context | Сохранить provenance/digest без второго проектного формата планирования | M |
| C3 точные approvals/revisions | S/H → H полномочия + S digest record поверх O контента; simplify | Approve/materialize | Готовность артефакта не равна одобрению человека; релевантные изменения инвалидируют approval | M |
| C3 epochs/amendments | S → O контент задач + S execution cursor; simplify | `_new_plan_epoch`, amendment | Сохранить историю и identity текущей работы; перенумерация не двигает cursor молча | M |
| C3 improvement/self-development | S/H → O контент change + S/H capability/activation; integrate | Методы и тесты improvement | Сохраняются явный триггер и изоляция successor | M |
| C4 execution/state/locks | S → S; retain | `_run_loop`, `resume`, `operation_lock` | Checkbox не является resumable invocation/commit checkpoint | H |
| C4 dashboard/timing | S → S исполнение + O прогресс задач; simplify | `status`, `dashboard`, `_record_timing` | Не допускать двух разных progress; честно показывать recovery action | M |
| C5 quota | S/H → S/H; retain | Provider/consume tests | Наличие файла или текст ассистента не дают разрешения | H |
| C6 processes/reports/diagnostic repair | S → S; retain | Runner, validators, `_invoke*` | Сохранить ограничение запуска и read-only classification; общая стратегия repair открыта | H |
| C7 verification/scope/Git/recovery | S/H → S/H; retain | Матрица контролей | Sync/archive не заменяют полные checks и точное transaction recovery | H |
| C8 live identity/handoff | S/H → S/H; retain | Binding/lease/update tests | Регистрация store не квалифицирует engine | H |
| C8 исторические compatibility routes | S → unresolved; unresolved | Cutover/state/scope recovery | Нужны данные о supported versions и retention; удаление не разрешено | M |
| C9 planning schemas | S → O формат артефактов + S boundary validators; integrate | Approval/admission/cold-start/backlog/improvement/epoch | Избежать двух payload-форматов; сохранить проверку authority/input | M |
| C9 runtime schemas | S → S; retain | Reports/policy/audit/grants/owner/engine/state | Сохранить версии и семантические проверки сверх JSON shape | H |
| C10 planning prompts | S → O workflows; delegate to OpenSpec | Cold-start/admission/backlog/improvement | Отдельная генерация исчезает только при сохранении provenance и ограниченного scope | M |
| C10 execution prompts | S → S с O context; integrate | Implement/architecture/diagnose/repair | Заменить жёсткие ticket paths проверенным context; сохранить ограничения ролей | M |
| C11 runtime tests/fixtures | S → S; retain | Пять модулей и fixtures | Нужны при любом владельце планирования; пробелы acceptance остаются явными | H |
| C11 documentation checks | S → S; retain | Checker/manifest/tests | Одна поддерживаемая operator EN/RU пара; датированный перевод отчёта отдельно | H |
| C12 текущие operator/backlog документы | S/H → S/H operations + O будущие changes; integrate | Guide/governance/backlog | Кандидаты бэклога не исполняются до выбора; операционные полномочия явны | M |
| C12 завершённые исторические planning docs | S → Git historical evidence; retire, кандидат | Статусы historical/governance | Позднее нужны решения о retention/coverage; здесь файлы не удаляются | M |
| C12 OpenSpec config/workflows | O → O; retain | Root/schema/generated skills | Один выбранный planning root, трактовка привязана к версии | H |

## 9. Дублирование истины и ошибки передачи управления

Это требования к возможной интеграции. Реализующего их adapter сейчас нет.

| Передача | Что перестанет быть источником истины планирования | Обнаружение расхождения до исполнения |
|---|---|---|
| Требования/design в O | Копии requirements/architecture payload Supervisor и их отдельные редактируемые оригиналы | Сохранять root/change identity и digests релевантных O входов; изменение инвалидирует соответствующее approval; несовпадающие копии отклонять |
| Декомпозиция задач в O | Отдельная редактируемая иерархия tickets/порядок плана и новые параллельные materializations | Привязать исполнение к устойчивой task identity и digest; обнаруживать rename/delete/reorder/dependency change; останавливать текущую работу при смене привязки |
| Генерация planning prompts в O | Отдельные cold-start/backlog/improvement templates как конкурирующий контракт | Проверять root/paths/schema возвращённого context и digests; неизвестный формат отклонять, а не угадывать mapping |
| Архив planning change в O | Архив содержимого планирования Supervisor как вторая каноническая история спек | Хранить ссылку на archived change/commit/digests в execution records; отдельно проверять archive/sync и runtime completion |

OpenSpec checkbox completion, завершение тикета Supervisor, успешный commit и remote
persistence — четыре разных факта. Интеграция должна сверять их с долговечными
acceptance evidence, а не копировать один boolean в обе стороны. Approval привязывается
к просмотренному контенту: иначе правка OpenSpec оставит устаревшее одобрение Supervisor
действующим. Store/root должен записываться, чтобы одинаковое имя change не разрешилось
в другом репозитории. Runtime archives продолжают отвечать за rollback и не удаляются
при архивировании planning change.

## 10. Кандидатная модель работы до плана миграции

Раздел содержит рекомендации, а не текущее поведение. Каждая функция имеет один
предлагаемый источник полномочий: O — source requirements, spec deltas, design,
контент задач и planning archive; S — execution cursor, process/verification/
checkpoint/Git state, quota consumption и recovery audit; H — продуктовый замысел,
существенные компромиссы, capability grants и разрешение необратимых операций.
Проектная политика ограничивает полномочия хоста. На границе передаются выбранные
root/change/task identity, digests контента, acceptance references и provenance
разрешений. S ссылается на O, не создавая второй редактируемый план; прогресс O
сверяется только с принятым результатом S. Существующие контроли S действуют до
замены отдельной разрешённой реализацией.

### Режимы строгости

Во всех трёх предлагаемых режимах сохраняются один писатель, явные полномочия,
identity checkpoint, учёт quota consumption, отсутствие повторных side effects,
безопасные Git transactions, защита секретов и обязательные acceptance checks.
Ни один режим не допускает generic force-state, автоматический повтор неизменившейся
ошибки или неявно разрешённую необратимую операцию.

| Режим | Дополнительные проверки/review | Условия и свидетельства |
|---|---|---|
| Исследование | По умолчанию read-only discovery; локальные одноразовые эксперименты в разрешённом scope; неизвестный замысел фиксируется, completion не объявляется | Обратимое изолированное исследование без persistent/public/trust-boundary изменения |
| Обычная стартап-разработка | Focused checks плюс обязательная регрессия; architecture review при существенном изменении границ; пользовательский gate при значимом intent/authority decision | Утверждённые ограниченные требования; tests/diff/content binding обосновывают автономные локальные решения |
| Защищённая/релизная работа | Более широкая регрессия, compatibility/rollback evidence и явное release/operator decision | Persistent data, public contracts, sensitive trust boundary, широкий operational impact либо protected/release policy |

Исторические compatibility checks нужны, когда их требует поддерживаемая legacy
версия или живой recovery record, а не просто потому, что существует старый тикет.
Какие маршруты уже не нужны, здесь не установлено; критерии и расписание вывода
относятся к исключённой дорожной карте.

### Маршрутизация решений

Сначала проверяются неоднозначность, полномочия/необратимость, затем blast radius,
public/data/trust boundary, operational cost, обратимость и существенность компромисса.
При пересечении маршрутов приоритет у пользовательского решения. Архитектурный
проход может подготовить варианты, но не выдать разрешение.

| Пример / условие | Маршрут | Необходимое основание |
|---|---|---|
| Переименование внутреннего helper или существующая локальная абстракция в рамках требований | Автономная реализация | Локальный обратимый diff и проверки; без новых public/data/trust/cost обязательств |
| Новая dependency, изменение границы компонента/public contract/persistent representation, существенное увеличение стоимости сервиса | Architecture review | Альтернативы, более простой вариант, анализ compatibility/risk/cost; пользовательское решение, если остаются существенно разные обязательства |
| Неоднозначность меняет продуктовый результат; разрушение data/history; credentials/grants; внешние обязательства; существенный компромисс/риск | Решение пользователя | Конкретные варианты и последствия; явный scope/authority; молчание не считается разрешением |
| Известная configured verification failure при прежнем checkpoint | Детерминированная остановка/проверка recovery | Точные существующие evidence; model repair только с разрешением и изменившейся гипотезой исправления |
| Legacy migration или активация engine | Architecture/qualification плюс operator go | Точная identity predecessor/compatibility/rollback, состояние покоя; это не обычный локальный рефакторинг |

### Экономия квоты без прогнозирования

Детерминированный preflight должен предшествовать расходованию квоты; уже выбранный
OpenSpec context и неизменившиеся evidence используются повторно. Модель не нужна
для механически разрешимых переходов. Новую попытку обосновывает изменение task digest,
checkpoint, сигнатуры failed check или явной гипотезы ремонта. Число попыток/вызовов
и время ограничиваются по работе и роли; исчерпание бюджета ведёт к остановке и
эскалации. Проектирование таких бюджетов ещё нужно; общего механизма сегодня не заявляем.

Метрики: authorized/started/completed calls по роли/задаче, повторные вызовы при
одинаковом content/checkpoint/failure signature, diagnostic/review calls,
детерминированные handoffs, остановки, время и записанный token usage, если доступен.
Источники — события контроллера и существующие outputs, с безопасными идентификаторами
и агрегатами; без вызовов модели ради учёта, секретов и текста промптов в метриках.
Сравнивать calls на принятую задачу и repeat-call rate нужно для сопоставимых scopes,
разделяя время модели и verification. TTL наблюдения определяют текущее разрешение,
но не предсказывают число оставшихся тикетов или будущую доступность. Для численной
экономии нужны runtime evidence и сопоставимый baseline; этот отчёт их не содержит.

## 11. Проверки и оставшиеся неизвестные

Сопутствующий JSON — статический индекс свидетельств, а не новый runtime-контракт.
Номера разделов, component IDs, измерения и строки классификации совпадают в EN/RU.
Это датированные снимки оценки вне единственной постоянно поддерживаемой пары
operator guides; translation manifest не меняется.

Проверки поставки: documentation governance, локальные Markdown-ссылки обоих отчётов,
наличие указанных code/test symbols, hashes исходников evidence, whitespace, strict
OpenSpec validation и существующий offline unit suite. 2026-11-18 эти проверки прошли; существующий набор выполнил **205 тестов** за
64.331 секунды с результатом `OK`. Успешный unit suite не является real Codex acceptance
receipt. Дорожная карта намеренно не выполнена, поэтому задача проверки полного
изменения 6.1 остаётся открытой.

Пробелы: реальная экономика запусков/квоты; завершение T21–T24 и real acceptance;
необходимый срок хранения legacy recovery; стабильная task identity при правках
OpenSpec; CLI subprocess или другой интерфейс интеграции; границы будущих режимов
строгости. Они ограничивают будущие проектные решения, но не факты исходников выше.
