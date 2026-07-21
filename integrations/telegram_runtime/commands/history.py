from __future__ import annotations

from ..formatter import format_history_v14


def history_response(task_service, namespace: str, argument: str) -> str:
    if not argument:
        limit = 5
    elif argument.isdigit() and 1 <= int(argument) <= 20:
        limit = int(argument)
    else:
        return "Укажи количество задач от 1 до 20. Например: /history 10"
    return format_history_v14(task_service.history(namespace, limit))
