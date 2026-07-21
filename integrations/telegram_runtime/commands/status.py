from __future__ import annotations

from ..formatter import format_task_status


def status_response(task_service, context, namespace: str) -> str:
    task_id = context.active_task_id()
    task = task_service.get(namespace, task_id) if task_id else None
    return format_task_status(task)
