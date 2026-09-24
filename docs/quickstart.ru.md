# Development Supervisor 1.x: краткая инструкция

Эта инструкция описывает текущую версию. Для чужого репозитория сначала прочитайте
[ограничения и сценарии принятия](limitations.ru.md): `init` не выполняет архитектурный
анализ и не импортирует произвольные документы.

## 1. Предварительные требования

- Linux/Unix-среда с `fcntl.flock`;
- Python 3;
- Git repository с хотя бы одним commit и настроенной возможностью создавать commits;
- `codex-cli 0.155.1` согласно текущему README;
- чистая policy branch;
- ручной доступ к достоверному Codex `/status` для ввода квоты.

Путь к standalone engine должен оставаться доступен проекту. После перемещения движка
обновите `.dev-supervisor/engine.json` повторной безопасной настройкой либо задайте
`DEV_SUPERVISOR_HOME`.

## 2. Сначала подготовьте проект

Для существующего проекта до `init` человек должен:

1. инвентаризировать код, зависимости, интерфейсы, данные, deployment и тесты;
2. отделить наблюдаемый AS-IS от желаемого TO-BE и технического долга;
3. утвердить authoritative architecture/product documents;
4. составить упорядоченный implementation plan;
5. создать bounded ticket document для каждого номера;
6. определить verification commands, protected paths, branch, milestones и human
   gates;
7. выбрать честный `bootstrap_ticket` и `initial_completed_tickets`.

Supervisor 1.x не выполняет эти шаги автоматически.

### Формат плана

Парсер ожидает Markdown table. Строка milestone начинается с числа, номера тикетов
находятся в третьей колонке:

```markdown
| Milestone | Tickets | Gate |
|---|---|---|
| 1 foundation | 01 → 02 → F03 | review |
| 2 delivery | 04–06 | release |
```

Для `T01` нужен ровно один файл вида
`docs/architecture/tickets/01-<slug>.md`; для `F03` — `f03-<slug>.md`. Практичный
ticket содержит цель, зависимости, acceptance criteria, явный scope и строку
ownership, например:

```markdown
- Files/modules: `src/example.py`, `tests/test_example.py`
```

Последний тикет плана не запускайте без заранее принятого ручного протокола: у 1.x нет
корректного `PLAN_DONE` transition.

## 3. Инициализация

### Новый небольшой репозиторий

Из репозитория движка:

```bash
./supervisor init /path/to/project
```

Это создаёт `dev`, default `dev-supervisor.json`, `.dev-supervisor/`, запись в
`.gitignore` и минимальные T01 plan/ticket. Scaffold — заготовка: до первого model run
замените placeholder task, настройте policy, проверьте созданные tracked files и
закоммитьте их.

### Существующий репозиторий

Подготовьте полную project-specific policy и выполните:

```bash
./supervisor init /path/to/project --policy /path/to/reviewed-policy.json
```

С supplied policy `init` не создаёт и не нормализует architecture documents. Он также
не проверяет policy общей schema. До первого запуска вручную проверьте все обязательные
ключи по [описанию конфигурации](architecture-as-is.ru.md#конфигурация-проекта).

`init` откажется перезаписывать существующие `dev` или `dev-supervisor.json`; default
init также откажется при конфликте с default plan/ticket. Это защита, а не ошибка,
которую следует обходить удалением данных.

## 4. Проверка после init

В управляемом репозитории:

```bash
./dev status
git status --short
```

Проверьте:

- `State: READY` и ожидаемый текущий ticket;
- правильную branch и clean tree после commit scaffold;
- существование всех authoritative documents и ticket file;
- команды verification вручную;
- allowlists/forbidden paths;
- milestones и reserves;
- путь движка в `.dev-supervisor/engine.json`.

## 5. Типичный рабочий цикл

Сначала перенесите только что увиденную достоверную квоту:

```bash
./dev quota set --five-hour 80 --weekly 70
./dev status
./dev run
```

Weekly dimension необязательна, но если передана, применяется соответствующий reserve.
Каждая запись одноразовая. Перед следующим model invocation понадобится новое
наблюдение:

```bash
./dev quota set --five-hour 78 --weekly 69
./dev resume
```

Не копируйте старое значение «для удобства»: TTL и consumption — часть safety model.

Успешный pipeline сам выполняет проверки, scope gate и commit. Не stage/commit-ьте
model delta вручную посередине pipeline, если конкретный human gate этого не требует.

## 6. Как читать остановку

Всегда начинайте с:

```bash
./dev status
```

Dashboard показывает phase, ticket, role/model, HEAD/dirty files, quota, checkpoint
counters, последний результат, forecast и следующие действия.

Частые случаи:

| Phase | Действие оператора |
|---|---|
| `QUOTA_CHECK_REQUIRED` | Получить новое trusted observation, `quota set`, затем `resume` |
| `QUOTA_LOW` | Подождать/освободить квоту, записать новое observation |
| `QUOTA_EXHAUSTED` | Не retry-ить до нового `/status`, более позднего чем rate limit |
| `PERIODIC_CHECKPOINT` | Проверить состояние; release либо осознанно открыть reconciliation/adoption |
| `HUMAN_GATE` | Выполнить требуемое решение/evidence/commit, затем release |
| `INTERRUPTED` | Проверить artifacts и неизменность tree, затем `resume` |
| `VERIFICATION_FAILED` | Прочитать названный log; исправлять только по документированному recovery path |
| `GIT_BLOCKED`/`SCOPE_BLOCKED` | Не делать reset; сопоставить HEAD, dirty paths, report и message |
| `REPORT_INVALID`/`DIAGNOSTIC_FAILED` | Использовать `resume` только если dashboard его рекламирует |
| `ARCHITECTURE_FAILED`/`SUPERVISOR_REPAIR_FAILED` | Требуется ручной анализ; штатного общего retry нет |

Run artifacts находятся в `.dev-supervisor/runs/<run-id>/`. Не редактируйте их для
«починки» transition: это уничтожит доказательность checkpoint.

## 7. Human gates

Обычный release:

```bash
./dev gate release --note "что проверено и почему разрешено продолжение"
./dev resume
```

Product-decision gate требует human-authored commit по операционному договору; guard
технически проверяет лишь изменение HEAD и clean tree, поэтому содержательная review
остаётся ответственностью человека. Evidence gate требует сначала настроенные
deterministic evidence checks и изменение только разрешённой evidence record:

```bash
./dev evidence check --ticket T30
./dev gate release --note "live evidence recorded: PASS"
./dev resume
```

На quiescent periodic checkpoint доступны два специальных процесса:

```bash
./dev gate reconcile-plan --note "почему перед текущим тикетом нужен prerequisite"
./dev gate adopt-architecture --note "какой внешний architecture-only commit проверен"
```

Оба механизма insertion-only: завершённый prefix и порядок существующих тикетов нельзя
переписать.

## 8. Environment и verification recovery

Эти команды применимы только когда message/state доказывают точное соответствие
policy-owned capability или сохранённому host failure:

```bash
./dev recover-environment --capability <configured-capability>
./dev recover-verification-failure
./dev reconcile-verification-evidence
```

Они не являются универсальным способом «пропустить тест». Любое противоречие должно
остановить процесс.

## 9. Безопасная остановка

```bash
./dev stop
```

Отключать машину безопасно только после явного acknowledgement quiescent state. Если
команда сообщает, что acknowledgement не получен, проверьте процесс и `./dev status`;
не считайте сохранённый stop request достаточным.

## 10. Новый цикл развития

После завершения старого плана не добавляйте сырые требования прямо во время model
run. Остановитесь между тикетами на quiescent checkpoint, проведите discovery и
architecture work отдельно, получите human approval и только затем добавьте новые
milestones/tickets через контролируемый переход. В 1.x нет полноценного rollover и
нет completed-plan state; практический новый цикл требует ручной миграции state/policy
или развития Supervisor 2.0. Подробности — [сценарий C](limitations.ru.md#сценарий-c-развитие-после-исходного-плана).
