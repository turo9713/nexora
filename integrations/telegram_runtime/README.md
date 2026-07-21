# Nexora Telegram Runtime Adapter

Owner-only Telegram-интерфейс поверх существующего Nexora Runtime и OpenClaw.
Адаптер не предоставляет Telegram-пользователю shell, root, Docker socket или
прямой доступ к Gateway.

## Nexora v1.4

Поток выполнения:

```text
Telegram Bot API
  -> bot.py (long polling, allowlist, callback routing)
  -> handlers.py (router)
  -> commands/ (команды и UX)
  -> services/ (task, progress, cancellation, approval, idempotency)
  -> storage/ (атомарное owner-isolated состояние)
  -> существующие Orchestrator + WorkflowEngine + AgentRunner
  -> OpenClawProvider -> Gateway /v1/responses
```

`Runtime Core`, schemas, workflow definitions, Provider и Transport не
изменяются. Задачи выполняются отдельным worker-потоком, поэтому `/status` и
`/cancel` доступны во время запроса к модели.

## Команды

- `/newtask <описание>` — создать новую задачу;
- обычный текст — продолжить активный диалог;
- `/status` — локальное состояние текущей задачи без LLM-вызова;
- `/history [1–20]` — последние задачи, по умолчанию 5;
- `/task <ID>` — безопасная карточка своей задачи;
- `/cancel` — запросить отмену активной задачи и инвалидировать approvals;
- `/reset` — очистить диалоговый контекст;
- `/menu` — показать главное меню;
- `/help` — показать справку;
- `/health` — безопасная инфраструктурная сводка;
- `/agents` — маршрут текущего workflow.

Меню: `🧠 Новая задача`, `📊 Статус`, `📋 История`, `🛑 Отменить`,
`🧹 Сбросить контекст`.

## Статусы и прогресс

Поддерживаются `NEW`, `CLARIFYING`, `QUEUED`, `PLANNING`, `IN_PROGRESS`,
`WAITING_APPROVAL`, `COMPLETED`, `FAILED`, `CANCELLED`, `EXPIRED`.

Процент показывает только крупный этап, а не ложную точность: создание — 0%,
уточнение — 10%, планирование — 20%, очередь — 25%, выполнение — 40%,
завершение — 100%. При ошибке, отмене и ожидании подтверждения сохраняется
последний известный процент.

## Подтверждения

Запросы на перезапуск сервисов, изменение Docker, deployment, публикацию,
удаление файлов, внешние сообщения и потенциально необратимые изменения БД
переводятся в `WAITING_APPROVAL`. Callback содержит только решение и случайный
`APR-XXXXXXXX`.

Approval:

- принадлежит owner namespace, задаче и текущей сессии;
- действует 10 минут;
- одноразовый;
- инвалидируется при `/cancel`;
- повторное нажатие не запускает действие повторно;
- фиксируется в защищённом audit log.

Подтверждение разрешает продолжить безопасный runtime-вызов. Опасные host-
операции всё равно не выполняются агентом: `tools=[]`, Docker socket и root
отсутствуют, external actions запрещены.

## Отмена и идемпотентность

`/cancel` выставляет cancellation flag, переводит незавершённую задачу в
`CANCELLED`, инвалидирует approvals и очищает контекст. Уже созданные результаты
не удаляются. Если HTTP-запрос уже выполняется, worker проверяет flag перед
следующим этапом и отбрасывает поздний результат.

Persistent idempotency применяется к Telegram `update_id`, callback,
workflow-turn и approval action. Статусы действия: `PENDING`, `RUNNING`,
`SUCCEEDED`, `FAILED`, `CANCELLED`.

## Контекст и хранение

Диалоговый контекст совместим с v1.3:

- TTL: 6 часов;
- максимум 12 сообщений;
- максимум 12 000 символов;
- каталог `runtime/state/telegram_sessions`: `700`;
- файл `active.json`: `600`;
- Telegram ID и токены не сохраняются.

Состояние v1.4 находится в `runtime/state/telegram_v14/`:

- `tasks/` — безопасные карточки и transitions;
- `approvals/` — одноразовые approvals;
- `actions/` — idempotency records;
- `audit/events.jsonl` — redacted audit.

Владелец изолируется HMAC namespace. Ключ находится только в read-only secret
`/run/secrets/namespace_key`. Все каталоги имеют права `700`, файлы — `600`;
JSON записывается через временный файл, `fsync` и `os.replace`.

## Безопасность и ошибки

Неизвестные сообщения получают только `ACCESS_DENIED`. Неизвестные callback
отклоняются до чтения task/approval state и не вызывают LLM.

Пользователь видит только безопасные коды: `NX_TIMEOUT`, `NX_PROVIDER_ERROR`,
`NX_VALIDATION_ERROR`, `NX_PERMISSION_DENIED`, `NX_TASK_NOT_FOUND`,
`NX_TASK_CANCELLED`, `NX_APPROVAL_EXPIRED`, `NX_INTERNAL_ERROR`.
Техническая ошибка проходит redaction перед audit log. Authorization, Bearer,
API keys, cookies, пароли, connection strings и private keys удаляются.

## Миграция

`python -m nexora.integrations.telegram_runtime.migrate_v13` импортирует только
sanitized metadata owner-задач из v1.3. Старые task/history файлы не изменяются и
не удаляются. Повторный запуск идемпотентен.

## Диагностика и тестирование

```sh
docker inspect --format '{{.State.Health.Status}}' nexora-telegram
docker logs --tail 100 nexora-telegram
/workspace/nexora/runtime/.venv/bin/python -m pytest -q \
  /workspace/nexora/integrations/telegram_runtime/tests
```

В логах нельзя публиковать tokens, Authorization headers или raw traceback.
Live smoke выполняется отдельным owner namespace/state-root и удаляет созданные
runtime test artifacts.

## Rollback

Pre-update backup:
Use the administrator-approved encrypted backup location; production paths are
not distributed in the public repository.

Fail-closed rollback script:
Use `scripts/rollback-release.sh --check <tag>` for public release validation.

Скрипт делает снимок v1.4, восстанавливает adapter/Compose v1.3 и пересоздаёт
только `nexora-telegram`. Gateway не останавливается и не пересоздаётся.

## Короткая инструкция Telegram

1. Отправьте `/newtask <описание>`.
2. Проверяйте выполнение через `/status`.
3. Отвечайте обычным текстом на уточняющие вопросы.
4. Для опасного действия используйте только inline-кнопки.
5. Историю смотрите через `/history`, результат — `/task <ID>`.
6. Для остановки используйте `/cancel`, для очистки диалога — `/reset`.
