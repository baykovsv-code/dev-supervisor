# Development Supervisor: уточнённый план версии 2.1

Исходное обсуждение: 2026-09-25  
Актуализация после выпуска 2.0: 2026-09-26

Статус: решения по границам версии приняты владельцем. Исполнение должно идти через
отдельный утверждённый plan epoch Supervisor 2.1, а не изменять уже выпущенную линию
2.0 задним числом.

## Что изменилось после исходного обсуждения

Supervisor 2.0 уже выпущен и активирован. Поэтому предложения, которые раньше
предлагалось вставить до T11/T12, переходят в 2.1. Старый engine 1.x и checksummed
cutover archive сохраняются как recovery evidence. Опубликованная Git history не
переписывается.

Перед началом нового epoch нужно один раз закрыть неисполняемый T99 sentinel точной
post-cutover reconciliation-командой. Она не должна запускать модель, создавать
фиктивный commit или быть общим `force state` механизмом.

## 1. Автоматическое чтение quota

В 2.1 добавляется машинный provider для capability-detected метода Codex app-server
`account/rateLimits/read`.

Принятый контракт:

1. Для каждого наблюдения Supervisor запускает отдельный короткоживущий app-server.
   Уже работающий daemon не используется.
2. Пятичасовое и недельное окна определяются по `windowDurationMins`, а не по позиции
   `primary`/`secondary`.
3. Supervisor нормализует только текущее наблюдение: `percent_left = 100 -
   usedPercent`. Прогноз доступности и количества будущих tickets не строится.
4. Ledger хранит источник, account identity, Codex/protocol identity и отдельные
   authorization records.
5. `ordinaryUsageAllowed=false`, отсутствующие или неоднозначные buckets, ошибка
   протокола, недоступный executable и ошибка авторизации не являются разрешением.
6. При невозможности машинного чтения сохраняется явный manual fallback через
   `./dev quota set`.
7. Unit tests используют fake JSON-RPC app-server и не обращаются к сети или реальной
   учётной записи.

## 2. Понятная и минимально достаточная документация

Английский `docs/operator-guide.md` остаётся нормативным. Его нужно проверить с точки
зрения нового пользователя, который не знает внутреннюю архитектуру: сначала цель,
установка, безопасный обычный цикл и типичные остановки; детали state machine и
recovery — после этого.

Русский `docs/operator-guide.ru.md` нужно переписать как ясное операторское
руководство, сверяя разделы с английским оригиналом. Текущий текст нельзя считать
достаточным только потому, что он проходит формальную проверку ссылок.

`translation-manifest.json` сохраняется, но только как маленький freshness-контроль
единственной пары EN/RU. Он фиксирует digest английского текста, просмотренного при
обновлении русского. Он не доказывает семантическую эквивалентность и не делает
русский текст нормативным.

Постоянный актуальный комплект:

- `README.md` с установкой, быстрым стартом, основными командами и статусом платформ;
- английский и русский operator guides;
- короткие invariants, trust boundaries и внешний контракт;
- действующие migration/recovery гарантии, пока соответствующие переходы
  поддерживаются;
- актуальный backlog;
- schemas и tests как executable specification.

После переноса действующих гарантий старые AS-IS документы, исторический backlog,
development narrative и specifications завершённых tickets 2.0 можно убрать из
default branch. Отдельный `archive/` не нужен: архивом служат tag 2.0 и Git history.

## 3. Публичная нейтральность

Из текущего дерева нужно убрать имя конкретного управляемого проекта, личные пути,
частные binding details и сведения о конкретном рабочем компьютере. Используются
нейтральные понятия: `legacy managed project`, `legacy 1.x checkpoint`, `generic
legacy fixture`, `self-hosted acceptance`.

История не переписывается. Нейтрализуется текущее состояние default branch. Общие
compatibility guarantees остаются в Supervisor; настройки отдельного проекта живут
вне публичного репозитория.

## 4. Generic compatibility и self-hosted acceptance

Нужны два разных уровня проверки:

1. Компактная синтетическая checksummed fixture проверяет legacy 1.x policy/state,
   read-only reconciliation, migration dry-run, rejection и rollback.
2. Self-hosted test запускает текущий Supervisor над изолированным checkout его
   собственного predecessor.

Нейтральным predecessor выбран точный commit первого ticket 2.1, который завершит
очистку публичного контекста и документации. Его hash записывается в acceptance
artifact после появления commit, а не угадывается заранее.

Минимальная fault matrix:

- модель вернула успех без изменения workspace;
- одна и та же verification ошибка повторяется без изменения checkpoint;
- recovery возвращает тот же checkpoint;
- quota refresh недоступен или противоречив;
- Codex прерван после durable quota consumption;
- resume повторён после commit boundary;
- architecture/diagnostic repair не устраняет причину;
- interrupted operation восстанавливается несколько раз.

Каждый сценарий получает жёсткий предел вызовов, ожидаемое quiescent/terminal state и
проверку отсутствия duplicate invocation, commit и quota consumption.

## 5. Реальный Codex acceptance

В 2.1 обязателен минимум один изолированный run с реально установленным Codex. Его
нужно проводить после готовности automatic quota provider и deterministic
self-hosted suite, но до финального release gate 2.1.

Run ограничивается числом model calls и временем, использует обычную quota
authorization, не касается live managed-project state и сохраняет redacted receipt.
Это operator-owned qualification, а не сетевой CI-тест.

## 6. macOS

В 2.1 допускаются review переносимости и deterministic/simulated platform-contract
tests. Проверка на реальном Mac не проводится вообще. Поэтому 2.1 не заявляет
поддержку macOS и не трактует симуляцию как qualification. Реальная Mac qualification
остаётся отдельным будущим backlog item.

## 7. Порядок реализации 2.1

1. `T20`: понятная документация, полный пересмотр русского guide, публичная
   нейтрализация и правила удаления устаревших материалов. Commit T20 становится
   нейтральным predecessor.
2. `T21`: automatic quota provider с отдельным короткоживущим app-server на каждое
   наблюдение и manual fallback.
3. `T22`: generic legacy fixture и bounded self-hosted acceptance matrix на точном
   predecessor T20.
4. `T23`: deterministic portability hardening; реальная Mac qualification явно
   отложена, macOS остаётся unsupported.
5. `T24`: минимум один real Codex acceptance run, финальная сверка документации и
   human release decision 2.1.

## Принятые решения

- Все оставшиеся идеи исходного обсуждения относятся к 2.1, а не к 2.0.
- Translation manifest сохраняется в упрощённой роли freshness alarm.
- Для quota всегда запускается короткоживущий app-server; daemon reuse отсутствует.
- Predecessor — точный verified commit T20.
- Реальный Codex acceptance проводится в T24.
- Проверки на реальном Mac в 2.1 нет; поддержки macOS не заявляем.
- Published Git history не переписывается.
