from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo


MAX_TEXT_LENGTH = 3800


def _clip(value: Any, limit: int = 500) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _message(lines: Iterable[str]) -> str:
    text = "\n".join(lines).strip()
    return text if len(text) <= MAX_TEXT_LENGTH else f"{text[: MAX_TEXT_LENGTH - 1]}…"


def format_welcome() -> str:
    return _message(
        [
            "Nexora Runtime",
            "",
            "Доступ разрешён владельцу. Адаптер создаёт задачи через существующий workflow runtime и продолжает активный диалог.",
            "",
            "Команды: /newtask /status /history /task /cancel /reset /menu /help",
        ]
    )


def format_help() -> str:
    return _message(
        [
            "Команды Nexora",
            "/newtask <описание> — новая задача",
            "/status — состояние текущей задачи",
            "/history [1–20] — последние задачи",
            "/task <ID> — подробности задачи",
            "/health — состояние платформы",
            "/cancel — отменить активную задачу",
            "/reset — очистить контекст",
            "/menu — открыть меню",
            "/help — показать справку",
        ]
    )


def format_platform_health(health: dict[str, Any]) -> str:
    return _message(
        [
            "Nexora Health",
            f"Runtime: {_clip(health.get('runtime'), 20)}",
            f"Telegram: {_clip(health.get('telegram'), 20)}",
            f"Storage: {_clip(health.get('storage'), 20)}",
            f"Database: {_clip(health.get('database'), 20)}",
            f"Agents: {int(health.get('agents_loaded', 0))} loaded",
            "Tasks:",
            f"Active: {int(health.get('active_tasks', 0))}",
            f"Completed today: {int(health.get('completed_today', 0))}",
            "Security:",
            f"Failed access: {int(health.get('failed_access', 0))}",
            f"Pending approvals: {int(health.get('pending_approvals', 0))}",
        ]
    )


def format_health(health: dict[str, str]) -> str:
    if not health:
        return "Проверка состояния временно недоступна."
    return _message(
        [
            "Статус Nexora",
            f"OpenClaw: {_clip(health.get('openclaw', 'unknown'), 40)}",
            f"Модель: {_clip(health.get('model', 'unknown'), 40)}",
            f"Telegram: {_clip(health.get('telegram', 'unknown'), 40)}",
            f"Последняя проверка: {_clip(health.get('last_successful_check_utc', 'unknown'), 80)}",
        ]
    )


format_status = format_health


def _local_time(value: Any, fallback: str = "—") -> str:
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(ZoneInfo("Europe/Moscow")).strftime("%d.%m %H:%M")
    except (ValueError, TypeError):
        return fallback


def _duration(created_at: Any, completed_at: Any) -> str:
    if not created_at or not completed_at:
        return "—"
    try:
        start = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
        seconds = max(0, int((end - start).total_seconds()))
    except (ValueError, TypeError):
        return "—"
    if seconds < 60:
        return f"{seconds} сек."
    return f"{max(1, round(seconds / 60))} мин."


def format_task_status(task: dict[str, Any] | None) -> str:
    if not task:
        return "Сейчас нет активной задачи.\nНачни новую командой:\n/newtask <описание задачи>"
    return _message(
        [
            "🧠 Текущая задача",
            f"ID: {_clip(task.get('task_id'), 100)}",
            f"Название: {_clip(task.get('title'), 120)}",
            f"Статус: {_clip(task.get('status'), 40)}",
            f"Этап: {_clip(task.get('stage'), 120)}",
            f"Прогресс: {int(task.get('progress', 0))}%",
            f"Создана: {_local_time(task.get('created_at'))}",
            f"Обновлена: {_local_time(task.get('updated_at'))}",
            f"Агент: {_clip(task.get('assigned_agent') or 'Developer', 80)}",
        ]
    )


def format_history_v14(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "📋 История задач пока пуста."
    lines = ["📋 Последние задачи"]
    for index, task in enumerate(tasks, start=1):
        start = _local_time(task.get("created_at"))
        end = _local_time(task.get("completed_at") or task.get("updated_at"))
        lines.extend(
            [
                f"{index}. {_clip(task.get('task_id'), 100)}",
                f"   {_clip(task.get('title'), 100)}",
                f"   {_clip(task.get('status'), 30)}",
                f"   {start}–{end}",
            ]
        )
    return _message(lines)


def format_task_details(task: dict[str, Any] | None) -> str:
    if not task:
        return "Задача не найдена или недоступна."
    result = task.get("result_summary") or "Результат пока не сформирован."
    return _message(
        [
            f"📄 Задача {_clip(task.get('task_id'), 100)}",
            f"Название: {_clip(task.get('title'), 120)}",
            f"Статус: {_clip(task.get('status'), 40)}",
            f"Создана: {_local_time(task.get('created_at'))}",
            f"Завершена: {_local_time(task.get('completed_at'))}",
            f"Длительность: {_duration(task.get('created_at'), task.get('completed_at'))}",
            f"Агент: {_clip(task.get('assigned_agent') or 'Developer', 80)}",
            f"Результат: {_clip(result, 2200)}",
        ]
    )


def format_task_outcome_v14(task: dict[str, Any]) -> str:
    heading = "✅ Задача завершена" if task.get("status") == "COMPLETED" else "🧠 Требуется уточнение"
    result = task.get("result_summary") or "Задача обработана."
    return _message(
        [
            heading,
            f"ID: {_clip(task.get('task_id'), 100)}",
            f"Статус: {_clip(task.get('status'), 40)}",
            f"Результат: {_clip(result, 2800)}",
            "",
            "Диалог активен — отправь следующий ответ или /cancel.",
        ]
    )


def format_safe_error(code: str, task_id: str) -> str:
    return _message(
        [
            "Не удалось завершить задачу из-за ошибки сервиса.",
            f"Код: {_clip(code, 40)}",
            f"Задача: {_clip(task_id, 100)}",
            "Можно повторить запрос или начать новую задачу.",
        ]
    )


def format_approval_request(approval: dict[str, Any]) -> str:
    return _message(
        [
            "⚠️ Требуется подтверждение",
            f"Действие: {_clip(approval.get('action_summary'), 300)}",
            f"Риск: {_clip(approval.get('risk_summary'), 500)}",
            f"Задача: {_clip(approval.get('task_id'), 100)}",
            "Срок действия подтверждения: 10 минут.",
        ]
    )


def format_agents(route: list[Any]) -> str:
    agents = [_clip(agent, 80) for agent in route if str(agent).strip()]
    if not agents:
        return "Список агентов временно недоступен."
    return _message(["Агенты workflow", *[f"• {agent}" for agent in agents]])


def format_tasks(tasks: list[dict[str, Any]], title: str = "Последние задачи") -> str:
    if not tasks:
        return f"{title}: пока пусто."
    lines = [title]
    for task in tasks:
        lines.append(
            f"• {_clip(task.get('title') or task.get('id'), 90)} — {_clip(task.get('status', 'UNKNOWN'), 30)}"
        )
    return _message(lines)


def extract_model_text(result: dict[str, Any]) -> str:
    details = result.get("details")
    if not isinstance(details, dict):
        return ""
    response = details.get("transport_response")
    if not isinstance(response, dict):
        return ""
    nested = response.get("response")
    if isinstance(nested, dict):
        response = nested
    output = response.get("output")
    if not isinstance(output, list):
        return ""

    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
    return "\n".join(texts)


def format_task_outcome(outcome: dict[str, Any]) -> str:
    task = outcome.get("task") if isinstance(outcome.get("task"), dict) else {}
    result = outcome.get("result") if isinstance(outcome.get("result"), dict) else {}
    lines = [
        "Задача обработана",
        f"ID: {_clip(task.get('id'), 100)}",
        f"Статус: {_clip(task.get('status', 'UNKNOWN'), 40)}",
    ]
    if result:
        result_text = extract_model_text(result) or result.get("summary", "готов")
        lines.extend(
            [
                f"Агент: {_clip(result.get('agent', 'unknown'), 80)}",
                f"Результат: {_clip(result_text, 2800)}",
            ]
        )
    return _message(lines)
