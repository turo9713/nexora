from __future__ import annotations

from ..formatter import format_task_details


def task_details_response(task_service, namespace: str, task_id: str) -> str:
    if not task_id:
        return "Используй: /task <ID>"
    return format_task_details(task_service.get(namespace, task_id.strip()))
