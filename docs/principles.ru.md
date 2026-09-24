# Development Supervisor 1.x: архитектурные принципы

Статус: краткое описание **фактически реализованных** принципов.

1. **Один тикет за раз.** Текущий ticket хранится в durable state; implementation
   prompt запрещает начинать следующий. Переход к следующему происходит только после
   verification, scope gate и commit.

2. **Fail closed.** Неизвестная квота, malformed report, расхождение fingerprint,
   неполное evidence или неоднозначный recovery останавливают pipeline. Supervisor не
   превращает отсутствие доказательств в разрешение.

3. **Проект владеет продуктом и policy; движок владеет оркестрацией.** Код движка не
   копируется в управляемый репозиторий. Проект хранит launcher, policy, план, тикеты и
   локальное runtime state.

4. **Git — граница транзакции.** Каждый run привязан к branch, starting HEAD, dirty
   paths и fingerprint. Supervisor сам stage/commit-ит проверенный delta и умеет
   распознать свой commit после crash.

5. **Отчёт модели — заявление, не доказательство.** Structured output ограничивает
   форму, код проверяет семантические инварианты, затем запускает независимые команды и
   сверяет реальные файлы.

6. **Минимальные полномочия ролей.** Implementation меняет только scope тикета;
   architecture — только разрешённую документацию; diagnostic read-only; repair —
   только allowlist движка после диагноза `SUPERVISOR_BUG`.

7. **Архитектура не придумывается молча.** Неоднозначность эскалируется в bounded
   architecture review, а недостающий product intent — в human gate.

8. **Каждый model call имеет отдельное разрешение по квоте.** Ручное trusted
   observation ограничено по возрасту и reserve и consumed до запуска. Recovery,
   diagnostic и repair не переиспользуют его.

9. **Checkpoints должны быть воспроизводимы.** State, run artifacts, quota audit,
   check logs и Git lineage позволяют продолжить конкретный этап, не повторяя уже
   доказанную работу.

10. **Прерывание сохраняет работу.** Stop, Ctrl+C, timeout и network failure не ведут к
    reset/stash/discard. Partial tree сохраняется и допускается только bounded recovery.

11. **Человек остаётся владельцем решений и внешних свидетельств.** Milestone,
    product-decision, owner-evidence и architecture-adoption gates нельзя обойти
    свободным текстом модели.

12. **Саморемонт уже, чем саморазвитие.** 1.x может устранить подтверждённый дефект
    собственной оркестрации с тестами и отдельным commit. Это не механизм изменения
    архитектуры продукта Supervisor и не управление разработкой 2.0.

13. **Один активный управляющий экземпляр.** Локальный lock запрещает два процесса для
    одного проекта. Для миграции 1.x → 2.0 этот принцип расширяется до запрета на
    одновременное управление или саморедактирование двумя версиями.

14. **Минимализм включает явные не-возможности.** 1.x не содержит package/plugin
    platform, remote update, произвольный requirements-to-plan pipeline или штатный
    lifecycle завершённого плана. Эти функции нельзя считать подразумеваемыми.

Подробности: [архитектура AS-IS](architecture-as-is.ru.md),
[state machine](state-machine.ru.md), [ограничения](limitations.ru.md).
