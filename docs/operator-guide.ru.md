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

Только для исторического дефекта count в protected-scope snapshot используйте
`./dev recover-protected-snapshot`. Команда может повторно обработать завершённый
read-only architecture PASS, лишь когда durable checkpoint доказывает, что
настроенный supervisor-control path вызвал старое несовпадение count product snapshot.
Она сверяет точные ticket, implementation и review run, HEAD, branch, набор и bytes
dirty paths, structured report, run artifacts, quota audit, product snapshot и полный
Git fingerprint. Она не вызывает model и не расходует quota, после чего возвращает
исходный review к обычным scope и commit gates. Missing, ambiguous, stale, changed
или не подходящее evidence fail closed без изменения preserved checkpoint. Это не
general override и не waiver evidence.
Также `resume` не изменяет не связанные с protected-scope checkpoints
`SCOPE_BLOCKED`, чтобы их исходные reason и evidence сохранялись для operator
reconciliation.

Engine update загружает successor отдельно, проверяет immutable identity и compatible
state/config/protocol, выполняет dry-run и tests, затем переключается только в
quiescent checkpoint после archive и read-only reconciliation. Rollback сначала
останавливает new generation. Unknown compatibility, second writer, dirty unsupported
migration state или невозможность сохранить guard — stop, preserve evidence, request
human decision.

## Qualified cutover 1.x и rollback

Полный нормативный английский [T12 runbook qualification и cutover](personal-assistant-qualification.md)
задаёт preflight, evidence lineage, rehearsal на isolated copy, abort, recovery и
final human gate. Второй operator должен независимо сверить evidence. Этот workflow
не разрешает менять live T30 gate; при различии текстов действует английский runbook.

Перед T12 оба operator подтверждают redacted checksummed fixture, все PASS reports
T00–T11/F09/F10/F11, отдельные clean immutable source/candidate engine checkouts,
единственный host writer lease и exact v4 `HUMAN_GATE` source. Выполните
`python3 scripts/check_documentation.py`: manifest должен быть fresh, а результат
проверяет только declared pair, links и freshness, не semantic equivalence. В пакет
final gate входят fixture/checksums, dry-run/apply/rollback receipts, pre/post
read-only status, product HEAD/fingerprint, test output, compatibility lineage и
documentation-check output; [T99 sentinel](architecture/tickets/99-cutover-sentinel.md)
не запускается под legacy controller.

Abort при stale manifest, missing receipt, changed source checksum, product diff,
duplicate invocation/commit, reused quota authorization или двух controller/lock.
Не исправляйте вручную state, binding, archive, quota или lock. До apply сохраните
dry-run evidence и оставьте legacy binding; после apply сначала остановите candidate
в quiescent state, выполните documented rollback и проверьте восстановленные
HEAD/fingerprint, v4 state, quota и единственный legacy lock.

Переход legacy → 2.0 выполняется только явно. До binding switch pinned AS-IS engine
продолжает работу без изменения: `status` и `resume` не запускают implicit conversion.
Сначала повторите процедуру только на isolated copy, до T12/final human gate. Допустим
лишь state version 4 в `HUMAN_GATE`: нет active run/pending commit, ticket gate совпадает
со state, а HEAD/fingerprint gate совпадают с product. Dirty tree допускается только с
таким preserved fingerprint. Unknown version, missing/ambiguous gate ownership, active
model/check/commit либо dirty mismatch отклоняются без записи.

Source engine должен быть clean на exact revision. Единственное документированное
исключение — untracked guard pinned AS-IS `.self-repair-disabled`: его checksum
сохраняется в predecessor receipt; не удаляйте guard ради выполнения cutover.

1. Подготовьте separate clean immutable checkout engine 2.0 и проверьте нужный gate.
2. Выполните `./dev legacy-cutover dry-run --candidate <2.0-engine>` и сохраните
   возвращённый `source_checksum` как reviewed receipt.
3. Human с host lease принимает go/no-go. Abort означает не выполнять apply: сохранить
   dry-run evidence и оставить legacy binding без изменения.
4. Для go: `./dev legacy-cutover apply --candidate <2.0-engine> --source-checksum
   <receipt> --go`; затем используйте только read-only `./dev status` и запишите решение.

Если новое поколение 2.0 активировано, его read-only status проверен и результат
принят, один раз выполните `./dev gate accept-cutover --note "..."`. Команда проверяет
cutover record, predecessor archive, binding, полный префикс завершённых тикетов,
финальный gate и HEAD. Она не вызывает модель и не создаёт commit. После принятия
прямой rollback в legacy 1.x закрывается, но checksummed archive сохраняется для
явного восстановления; новая разработка всё равно требует отдельного утверждённого
plan epoch.

Archive `.dev-supervisor/legacy-cutover-archives/` сохраняется и содержит checksummed
engine receipt/revision, binding, policy, state, quota ledger, run artifacts, Git
HEAD/branch/fingerprint/product snapshot и observed lock authority. Конверсия quota
invalidates every legacy authorization: consumed authorization никогда не используется
повторно. Workflow не удаляет predecessor archive.

При no-go сначала остановите new controller и достигните quiescent checkpoint, затем
holder lease запускает `./dev legacy-cutover rollback`. Он восстанавливает archived
legacy binding, policy, state и quota ledger, сохраняет product HEAD/working tree и
оставляет только restored legacy lock authority. Не редактируйте вручную archive,
binding, state, quota или lock для принудительного перехода/rollback.

Подробнее и точные текущие bootstrap commands — в [английском operator guide](operator-guide.md),
[architecture](architecture/architecture.md) и соответствующем ticket. До final gate
не выполняйте T99 и не переключайте live binding.
