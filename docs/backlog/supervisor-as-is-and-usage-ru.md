# Задача: описать AS-IS архитектуру и применение Development Supervisor

Статус: **исследование и документация выполнены** 2026-09-24 на коммите
`854083f51c9aedf33ec2d9654fc67aacff84af8a`.

Код Supervisor в рамках задачи не изменялся. Исследованы `supervisor.py`, launchers,
prompts, schemas, README, MIGRATION и тесты; выполнены все 156 тестов.

## Результаты

- [Подробная архитектура AS-IS](../architecture-as-is.ru.md)
- [State machine](../state-machine.ru.md)
- [Краткие архитектурные принципы](../principles.ru.md)
- [Краткая инструкция по применению](../quickstart.ru.md)
- [Ограничения и обязательные сценарии](../limitations.ru.md)
- [Предлагаемая архитектура Supervisor 2.0](../architecture/architecture.md)

Последующие пользовательские требования вынесены в отдельный
[англоязычный index требований Supervisor 2.0](../architecture/requirements-index.md).
Они не меняют выводы AS-IS и
должны пройти самостоятельный architecture review до реализации.

## Цель и покрытие

Комплект документов отвечает на следующие вопросы:

1. как устроен действующий Supervisor 1.x;
2. какие автоматы, состояния, guards и управляющие события существуют;
3. каковы фактические архитектурные принципы;
4. как подключить подготовленный новый или существующий проект;
5. где заканчивается автоматизация и начинается ручная работа;
6. насколько 1.x применим к существующим и развивающимся проектам;
7. как безопасно перейти к 2.0 без одновременного управления двумя версиями.

## Основные выводы AS-IS

Supervisor 1.x — standalone локальный оркестратор одного Git-репозитория и одного
тикета за раз. Он отделяет engine от managed project, использует одноразовую ручную
quota authorization, запускает Codex в workspace sandbox, валидирует structured
reports, выполняет детерминированные проверки, сверяет exact file scope и сам создаёт
commit.

Recovery основан на persisted state, run artifacts, Git HEAD и fingerprints. Human
gates, periodic checkpoints, diagnostic classification и bounded repair реализованы,
но общий requirements/discovery workflow, импорт чужих планов, завершённый plan
lifecycle и upgrade protocol отсутствуют.

`bounded self-repair` исправляет только подтверждённый `SUPERVISOR_BUG` в чистом
engine repository. Он не является механизмом разработки Supervisor 2.0.

## Оценка обязательных сценариев

### Сценарий A. Существующий репозиторий без архитектурных документов

Оценка: **не поддерживается end-to-end**.

`init` создаёт launcher, policy, runtime binding/state и минимальный placeholder plan,
но не проводит inventory, не реконструирует AS-IS, не отделяет technical debt от
принятой архитектуры и не создаёт trustworthy plan. До подключения требуется ручное
исследование, human-reviewed architecture baseline, декомпозиция и policy.

Полный разбор: [сценарий A](../limitations.ru.md#сценарий-a-существующий-репозиторий-без-архитектурных-документов).

### Сценарий B. Существующий репозиторий с документами другого формата

Оценка: **поддерживается частично после ручной миграции**.

Произвольные документы можно перечислить как authoritative, но plan parser и ticket
naming жёсткие. Importer, ID mapping и semantic normalization отсутствуют. Нужен
канонический Supervisor-compatible plan/index, однозначные ticket files и ручная
проверка пробелов/противоречий.

Полный разбор: [сценарий B](../limitations.ru.md#сценарий-b-документы-другого-формата).

### Сценарий C. Развитие проекта после выполнения исходного плана

Оценка: **поддерживается частично до границы; завершение плана не поддерживается**.

Periodic checkpoint позволяет ограниченно вставить prerequisite или принять внешний
architecture-only commit. Но 1.x не превращает сырые требования в архитектуру и план,
не версионирует plan cycles и не имеет состояния `PLAN_DONE`. После commit последнего
тикета `_next_ticket` завершается ошибкой. Новый цикл требует отдельного discovery и
human design gate, затем проверенной ручной миграции либо 2.0.

Полный разбор: [сценарий C](../limitations.ru.md#сценарий-c-развитие-после-исходного-плана).

### Сценарий D. Архитектура, реализация и переход на Supervisor 2.0

После архитектурного разбора AS-IS, выявления недостатков и формирования целей
развития необходимо:

1. выстроить и утвердить архитектуру TO-BE Supervisor 2.0;
2. реализовать 2.0 как обычный versioned продукт;
3. при желании использовать pinned Supervisor 1.x как внешний controller реализации,
   но только если это возможно без существенной доработки 1.x;
4. квалифицировать state migration, cutover, rollback и работу на копии
   `personal-assistant`;
5. привести живой `personal-assistant` к quiescent checkpoint и полностью остановить
   1.x;
6. архивировать точную revision, policy, state и artifacts 1.x read-only;
7. offline и атомарно перевести `personal-assistant` на 2.0 без изменения product HEAD
   и без потери plan/gate/history lineage;
8. после human go/no-go оставить 2.0 единственным controller;
9. разрешить 2.0 дальше дорабатывать себя только через его обычную архитектуру,
   общепринятый tracking, tickets, проверки и human gates, сохраняя минимализм.

Непереговорный инвариант: **не существует стадии, когда Supervisor 1.x и Supervisor
2.0 одновременно управляют одним проектом, правят друг друга или оба участвуют в
самоизменении 2.0**. Read-only rehearsal на копии допустим; dual control живого
репозитория — нет. Rollback сначала полностью выключает 2.0 и лишь затем возвращает
архивированный 1.x.

Оценка AS-IS: **частично как внешний implementation controller; сам upgrade/cutover
не реализован**. Подробности и критерии бесшовного перевода `personal-assistant`:
[анализ сценария D](../limitations.ru.md#сценарий-d-переход-от-supervisor-1x-к-supervisor-20)
и [предлагаемая архитектура 2.0](../architecture/architecture.md).

## Подтверждённые ограничения, важные для 2.0

- нет общей JSON Schema и полного preflight для policy/state;
- нет `PLAN_DONE`, plan epochs и нового development cycle;
- нет discovery/design lifecycle из сырых требований;
- plan/ticket formats жёстко заданы regex/naming convention;
- нет upgrade, export/import, state conversion и archive protocol;
- engine binding фиксирует path, но не immutable version identity;
- bounded self-repair уже и принципиально отличается от self-development;
- path ownership извлекается эвристически из ticket prose;
- artifact retention/redaction не специфицированы;
- поле `forecast.fallback_ticket_hours` фактически не используется;
- локальная блокировка защищает один host, но не определяет межверсионный cutover.

Полный каталог с последствиями, обходами и приоритетами P0–P2 находится в
[limitations.ru.md](../limitations.ru.md#каталог-существенных-ограничений).

## Методика и доказательства

При исследовании:

1. фактические переходы сверялись по реализации, а не выводились из README;
2. prompts и schemas рассматривались как часть role contract;
3. тесты использовались как подтверждение, но не как полная спецификация;
4. отдельно проверялись Git boundaries, quota consumption, crash recovery, human
   gates, diagnostic и external repair;
5. предположения о 2.0 отделены от реализованного AS-IS;
6. существенные утверждения в результатах снабжены ссылками на код, тесты или
   существующие документы.

Проверка:

```text
python3 -m unittest discover -s tests -v
Ran 156 tests in 20.327s
OK
```

## Критерии готовности

- [x] документы написаны на русском языке и связаны между собой;
- [x] AS-IS подтверждён кодом и текущими тестами;
- [x] связанные автоматы и runtime evidence описаны отдельно;
- [x] есть короткая инструкция и явная граница ручной подготовки;
- [x] каждому обязательному сценарию дана однозначная оценка;
- [x] для неполной поддержки названы ручные шаги, риски и направления 2.0;
- [x] bounded repair отделён от разработки и self-development 2.0;
- [x] зафиксирован single-controller cutover для `personal-assistant`;
- [x] в рамках задачи код не менялся.

Следующая самостоятельная работа — human review результатов, утверждение требований и
детальная TO-BE архитектура 2.0. Реализация должна начинаться только после этого gate.
