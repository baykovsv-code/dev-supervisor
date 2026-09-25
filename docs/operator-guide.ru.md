# Руководство оператора Development Supervisor

Это поддерживаемый русский операторский перевод [нормативного английского
руководства](operator-guide.md). Полный нормативный комплект документации Supervisor
2.0 — английский; при различии текстов применяется английский документ. Перевод
проверяется на объявленную пару и свежесть, но не на семантическую эквивалентность.

## Назначение и границы

Supervisor управляет одним репозиторием одним контроллером. Engine, managed project,
host-local runtime и canonical remote — разные границы. Git не является distributed
lock. До T12 live `personal-assistant` использует отдельный immutable AS-IS engine;
разрабатываемый checkout не получает над ним власть.

## Основной порядок работы

Проверяйте `./dev status` до действий. Жизненный цикл: review требований и
архитектуры, `PLAN_READY`, выполнение тикета, `PLAN_COMPLETED`, review backlog и новый
утверждённый plan epoch. Завершённый план не запускает модель и не выбирает новую
работу сам. Backlog становится тикетом только после ограниченного выбора, анализа
зависимостей и архитектурного воздействия, human approval и нового immutable epoch.

State, approvals, epochs, engine identity и audit events versioned. Неизвестная,
более новая, неоднозначная или невалидная версия останавливается без записи. Dry-run
миграции не меняет состояние; apply, rejection и rollback требуют документированного
workflow.

## Конфигурация и безопасность

Конфигурация versioned и preflight-validated. `self_modification`,
`user_requested_modification` и `repository_push` независимы, default-off и
fail-closed. Repository policy может только ограничить host grant, но не включить его.
Неизвестные keys, противоречия, invalid ranges, отсутствующие grants и secrets в
конфигурации запрещают действие до модели или remote mutation. Status/audit показывает
effective redacted configuration и provenance.

Одна модель не утверждает architecture, не выдаёт capability и не расширяет scope.
Self-development создаёт и проверяет successor в isolated checkout; executing
generation не изменяется. Activation — отдельный quiescent human-approved cutover с
rollback, без двух контроллеров одного проекта.

## Команды, quota и gates

Используйте `./dev status` для read-only проверки и `./dev quota set --five-hour
<percent> --weekly <percent>` только с текущим trusted observation. High observation
может разрешить ограниченные calls в TTL, medium требует fresh snapshot для каждого
call, low/unknown блокирует. Нет forecast quota, reset time или capacity; каждый call
имеет audit authorization.

`HUMAN_GATE` и periodic checkpoint не обходятся `resume` или quota set. До release
проверьте HEAD, tree, ticket, evidence и точный gate. Не редактируйте вручную state,
checkpoint или artifacts; сохраняйте evidence и используйте соответствующий human,
architecture или recovery workflow.

## Commit и push

После verification и scope validation Supervisor создаёт local commit и сохраняет его
identity. Не amend/rebase/squash/force-push этот lineage. Пока push disabled, результат
— `LOCALLY_COMMITTED`, не remote persistence. При enabled push host-owned remote name,
credential-free URL identity и target branch должны совпасть с checked-out и
repository-restricted branch. Пушится только verified commit; completion наступает
только после подтверждения его reachability на remote. Ошибки сети, credentials,
authorization, protection или non-fast-forward сохраняют local commit и дают
actionable status. Retry и interrupted confirmation idempotent; force-push запрещён.

## Recovery и ограничения

Recovery сверяет durable checkpoint, artifacts, HEAD, fingerprint и state; он не
повторяет без изменений модель или failed deterministic check. Для generic
`VERIFICATION_FAILED` допустимо только явное audited same-ticket recovery: точная
model checkpoint, ровно один текущий failed check и durable log должны совпасть. Оно
не расходует quota и не вызывает модель; repair затем проходит полный suite, scope и
commit gates. Host-verification handling строже. Missing, stale или altered evidence
останавливает процесс.

Engine update загружает successor отдельно, проверяет immutable identity и compatible
state/config/protocol, выполняет dry-run и tests, затем переключается только в
quiescent checkpoint после archive и read-only reconciliation. Rollback сначала
останавливает new generation. Unknown compatibility, second writer, dirty unsupported
migration state или невозможность сохранить guard — stop, preserve evidence, request
human decision.

Подробнее и точные текущие bootstrap commands — в [английском operator guide](operator-guide.md),
[architecture](architecture/architecture.md) и соответствующем ticket. До final gate
не выполняйте T99 и не переключайте live binding.
