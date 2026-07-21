from __future__ import annotations


def cancel_response(cancellation_service, context, namespace: str) -> str:
    task_id = context.active_task_id()
    if not task_id:
        return "Нет активной задачи для отмены."
    cancelled, task = cancellation_service.cancel(namespace, task_id)
    if not cancelled:
        return "Нет активной задачи для отмены."
    return (
        f"🛑 Задача {task['task_id']} отменена.\n"
        "Созданные файлы не удалялись.\n"
        "Для новой задачи используй:\n/newtask <описание>"
    )
