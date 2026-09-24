# Development Supervisor 1.x: ограничения и сценарии применения

Статус: **AS-IS assessment** на коммите
`854083f51c9aedf33ec2d9654fc67aacff84af8a`.

Оценки означают:

- **поддерживается** — существует прямой, проверенный кодом и тестами workflow;
- **частично** — полезные механизмы есть, но обязательны ручные шаги или остаётся
  неподдержанный участок;
- **не поддерживается** — безопасного штатного end-to-end workflow нет.

## Итог по обязательным сценариям

| Сценарий | Оценка 1.x | Краткий вывод |
|---|---|---|
| A. Существующий repo без архитектурных документов | **не поддерживается end-to-end** | `init` создаёт placeholder scaffold, но не реконструирует AS-IS и не отличает debt от архитектуры |
| B. Документы другого формата | **частично, после ручной миграции** | Supervisor читает только configured authoritative files и жёсткий формат plan/tickets; importer отсутствует |
| C. Новый цикл после исходного плана | **частично до границы, завершение не поддерживается** | Есть periodic insertion/adoption, но нет requirements-to-architecture и `PLAN_DONE`; последний тикет вызывает ошибку |
| D. Проектирование, реализация и переход на Supervisor 2.0 | **частично как внешний проект; миграция не реализована** | 1.x можно условно использовать лишь как pinned controller обычной реализации; cutover, state conversion и self-development 2.0 предстоит спроектировать |

## Сценарий A. Существующий репозиторий без архитектурных документов

### Ответ

Supervisor 1.x сам не проводит repository inventory, не реконструирует архитектуру и не
создаёт trustworthy исходный план. Default `init` создаёт лишь минимальную таблицу с
T01 и текст «Define the first bounded project-owned implementation task»
([supervisor.py:490–542](../supervisor.py#L490-L542)). Это bootstrap filesystem, а не
discovery.

### Обязательная ручная подготовка

1. Зафиксировать code/dependency/API/data/deployment/test inventory.
2. Описать фактический AS-IS независимо от намерений и желаемого TO-BE.
3. Завести issues/risks для debt и неизвестных; не объявлять существующее поведение
   автоматически правильным.
4. Утвердить authoritative documents и decision owners.
5. Декомпозировать первый безопасный bounded plan и ticket set.
6. Настроить policy, commands, protected paths, branch, gates и исходный frontier.
7. Запустить `init --policy`, проверить и закоммитить control surface до первого model
   invocation.

Без этих шагов `bootstrap_ticket` — лишь строка, а model получит недостаточное или
ложно authoritative основание.

### Безопасная исходная точка

Выбирайте clean reviewed commit, где тесты воспроизводимы. `initial_completed_tickets`
должны означать реально принятые элементы именно нового authoritative plan, а не все
исторические commits. Нерешённый debt должен быть явным ограничением/тикетом/ADR, а не
молчаливой частью baseline.

### Кандидаты 2.0

- read-only inventory mode;
- evidence-linked AS-IS draft;
- review gate до объявления документов authoritative;
- importer/bootstrap state machine, отделённый от implementation;
- baseline risks/debt register.

## Сценарий B. Документы другого формата

### Ответ

Supervisor может включить любые существующие файлы в `authoritative_documents`, но
план и ticket lookup не являются расширяемыми. Plan parser читает только numeric
Markdown-table rows и third column, ticket resolver требует naming convention
([supervisor.py:2402–2418](../supervisor.py#L2402-L2418),
[supervisor.py:4689–4713](../supervisor.py#L4689-L4713)). Importer, mapping IDs и
semantic consistency checker отсутствуют.

### Ручная нормализация

- выбрать один канонический plan либо создать thin Supervisor-compatible index;
- отобразить прежние identifiers на `TNN`/`FNN`; исходные IDs сохранить внутри ticket
  docs и commit history;
- создать по одному однозначному ticket file;
- явно перечислить dependencies, acceptance и owned paths;
- выявить противоречия между документами до объявления их authoritative;
- перенести completed frontier в policy/state только после review;
- настроить commands и gates.

Можно сохранить историю и старую структуру как reference, но 1.x не сохранит её
семантику автоматически. Дублирование номера, непривычный формат или несколько ticket
files приводят к stop, а не к интерактивному mapping.

### Кандидаты 2.0

- versioned planning adapter/import contract;
- stable external ID + internal execution ID;
- dry-run validation report;
- contradiction/gap registry;
- explicit migration manifest с provenance.

## Сценарий C. Развитие после исходного плана

### Ответ

Часть механики уже есть: на between-ticket `PERIODIC_CHECKPOINT` человек может открыть
bounded architecture plan reconciliation либо принять внешний architecture-only commit.
Оба пути разрешают только вставить pending prerequisites между completed frontier и
deferred current ticket, не переставляя старый план
([supervisor.py:4745–4958](../supervisor.py#L4745-L4958),
[supervisor.py:5960–6137](../supervisor.py#L5960-L6137)).

Но полноценный новый lifecycle не поддержан:

- сырые требования не превращаются в product decisions, TO-BE architecture,
  milestones и tickets;
- discovery/design не имеет отдельного lifecycle и approval contract;
- нет plan version/epoch;
- нет состояния `PLAN_DONE`;
- после успешного commit последнего ticket `_next_ticket` выбрасывает
  `SupervisorError`; commit уже мог быть создан, а state не финализирован
  ([supervisor.py:4654–4687](../supervisor.py#L4654-L4687),
  [supervisor.py:4960–4968](../supervisor.py#L4960-L4968)).

### Безопасный ручной процесс для `personal-assistant`

До исправления lifecycle не доводить 1.x вслепую до финального ticket transition.
На последнем устойчивом between-ticket checkpoint:

1. остановить автоматическое исполнение;
2. сохранить state/runtime backup и точный HEAD;
3. провести discovery и TO-BE design вне implementation run;
4. human-review/commit новой архитектуры и versioned plan;
5. вручную определить новый current ticket и completed frontier через отдельно
   проверенный migration procedure;
6. только затем продолжить выполнение.

Это обходной путь, не штатная команда. Предпочтительный долгосрочный ответ — 2.0 с
явными `PLAN_COMPLETED`, `DISCOVERY`, `DESIGN_REVIEW`, `PLAN_READY` и plan epochs.

## Сценарий D. Переход от Supervisor 1.x к Supervisor 2.0

### Желаемая модель

После завершённого AS-IS разбора недостатки и цели развития становятся входом в
отдельную, human-reviewed архитектуру TO-BE Supervisor 2.0. Затем 2.0 реализуется как
обычный versioned продукт. Supervisor 1.x допустимо использовать для этой реализации
только если он работает как зафиксированный внешний controller и не требует
существенных доработок ради самого сценария.

После qualification выполняется один контролируемый cutover:

1. `personal-assistant` приводится к quiescent migration checkpoint;
2. 1.x полностью останавливается;
3. его runtime и engine revision архивируются read-only;
4. state/control binding атомарно переводятся на 2.0 по заранее проверенному migration
   contract;
5. 2.0 проходит smoke/reconciliation на неизменном product HEAD;
6. 1.x выводится из эксплуатации и больше не управляет проектом;
7. дальнейшее саморазвитие 2.0 идёт только под 2.0, через его обычные architecture,
   planning, ticket, verification и human-gate механизмы.

**Запрещённое состояние:** нет ни одного интервала, в котором Supervisor 1.x и
Supervisor 2.0 одновременно управляют одним проектом, правят друг друга или оба
участвуют в self-modification 2.0. Rollback — это остановить 2.0 и отдельно вернуть
архивированный 1.x, а не запустить их параллельно.

### Что умеет 1.x и чего не умеет

1.x уже отделён от managed repo и может управлять обычным внешним repository через
launcher/binding. Поэтому им **условно** можно реализовывать 2.0 в отдельном рабочем
контуре, если архитектура 2.0 заранее принята, tickets совместимы с форматом 1.x, а
сам 1.x остаётся pinned и clean.

Но штатного upgrade protocol нет:

- нет versioned engine compatibility/migration manifest;
- `engine.json` содержит только filesystem path;
- нет offline state converter или schema validation;
- нет dual-read validation без dual control;
- нет cutover/rollback command;
- нет archive contract;
- bounded self-repair 1.x предназначен для конкретного `SUPERVISOR_BUG`, а не для
  создания следующего поколения;
- self-development 2.0 ещё не имеет архитектуры и safety proof.

Следовательно, end-to-end сценарий сейчас **не реализован**. Архитектурный и
операционный план вынесен в
[предлагаемой архитектуре Supervisor 2.0](architecture/architecture.md).

### Критерии бесшовности для `personal-assistant`

Cutover считается бесшовным, только если одновременно доказано:

- product HEAD и product working-tree fingerprint не изменились из-за миграции;
- current plan epoch, completed frontier, current/deferred ticket и закрытые gates
  однозначно перенесены либо явно завершены человеком;
- незавершённый model/verification/commit отсутствует; миграция происходит только из
  допустимого quiescent state;
- audit/history 1.x сохранены read-only и связаны с первым state 2.0;
- новая binding указывает на точную immutable build/revision 2.0;
- одновременно существует ровно один active controller и один lock authority;
- smoke test не делает product commit и подтверждает status/reconciliation;
- rollback заранее отрепетирован на копии и также соблюдает single-controller rule.

## Каталог существенных ограничений

| Ограничение AS-IS | Причина | Последствие | Ручной обход | 2.0 |
|---|---|---|---|---|
| Нет общей policy schema/preflight | Прямой доступ к dict keys | Ошибки проявляются поздно | Review fixture/default и dry-run `status` | Обязательная versioned schema и validator |
| Нет `PLAN_DONE` | `_next_ticket` требует successor | Последний commit не финализирует state | Остановиться до границы, ручная миграция | Явное завершение/новый epoch |
| Нет discovery/requirements pipeline | Architecture role намеренно bounded | Сырые требования нельзя безопасно отдать `run` | Внешний human-led design | Отдельные discovery/design states |
| Жёсткий Markdown parser и naming | Regex/table convention | Чужие планы не импортируются | Thin canonical index/manual mapping | Planning adapters + import manifest |
| State без schema/event replay | Один JSON snapshot и узкая миграция | Сложный upgrade/recovery | Backup + offline reviewed conversion | Versioned state/events/migrations |
| Engine binding — локальный path | Минимальный standalone launcher | Move/reclone требует ручной привязки; revision не pinned в файле | `DEV_SUPERVISOR_HOME`, ручная проверка commit | Immutable engine identity/version |
| Только manual quota | Нет machine-readable provider | Human step перед каждым model call | Trusted `/status` + `quota set` | Provider interface с audit, сохраняя fail-closed |
| Quota reset timestamps не авторизуют | Safety требует нового observation | Нельзя авто-resume после reset | Получить новый status | Явный trusted provider protocol |
| Локальный `flock` | Single-host design | Нет distributed/multi-host coordination | Один host/process | Не добавлять распределённость без реальной нужды |
| Model names/version CLI зашиты policy/README | Нет capability negotiation | Upgrade Codex/model может сломать schema/flags | Ручная qualification | Compatibility matrix/preflight |
| Architecture role не делает общий redesign | Bounded blocker safety | Нельзя развить архитектуру из сырых требований | Внешний RFC/human gate | Design lifecycle, не расширение blocker prompt |
| Self-repair требует clean engine repo | Repair commit должен быть изолирован | Любая незакоммиченная engine doc блокирует repair | Содержать engine clean | Отдельный immutable runner/worktree policy |
| Repair allowlist фиксирован в коде | Минимизация полномочий | Новая структура engine потребует code change | Human repair/migration | Architecture-owned manifest с hard ceilings |
| Path ownership извлекается из одной строки ticket | Простая эвристика | Неполные/нестандартные docs ослабляют later-ticket guard | Строгий шаблон и review | Typed ticket schema |
| Нет retention/redaction policy для artifacts | Локальный runtime считается доверенным | Prompts/logs могут расти или содержать чувствительный контекст | Ограничить docs, архивировать защищённо | Retention/classification/redaction contract |
| Forecast использует только observed min/max | Минималистичная эвристика; fallback field мёртв | ETA малоинформативен | Считать ориентиром | Удалить либо честно специфицировать |
| Нет официальной команды export/import runtime | Extraction ориентирован на локальность | Миграция проекта/engine ручная | Backup всего `.dev-supervisor` | Offline export/import с checksums |
| Product-decision gate проверяет смену HEAD, но не автора/смысл commit | Git guard доказывает только lineage | Ошибочный commit может формально открыть release | Обязательная human review note и commit inspection | Typed decision record и проверяемая связь с gate |

## Приоритеты развития

### P0 — корректность lifecycle и миграционная безопасность

- `PLAN_DONE` и versioned plan cycles;
- policy/state schemas и preflight;
- точная спецификация quiescent migration states;
- offline 1.x → 2.0 converter, audit link и rollback;
- single-controller invariant, включая self-development;
- тест qualification на реальной копии `personal-assistant`.

### P1 — принятие существующих проектов

- read-only inventory и bootstrap assessment;
- document/ticket import manifest;
- discovery/design/human approval до implementation;
- typed ownership/dependencies/acceptance.

### P2 — эксплуатация без разрастания системы

- engine compatibility preflight;
- artifact retention/redaction;
- quota provider abstraction только при наличии надёжного источника;
- устранение мёртвых/неиспользуемых config fields;
- документация recovery как machine-checkable capabilities.

Каждая возможность должна проходить проверку на минимализм: добавлять новый механизм
только когда существующий guard или обычный Git/документированный human step не решает
задачу безопасно.
