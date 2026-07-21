from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


VALID_STATUSES = {
    "NEW",
    "CLARIFYING",
    "QUEUED",
    "PLANNING",
    "IN_PROGRESS",
    "WAITING_APPROVAL",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "EXPIRED",
}
TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED", "EXPIRED"}
DEFAULT_PROGRESS = {
    "NEW": 0,
    "CLARIFYING": 10,
    "PLANNING": 20,
    "QUEUED": 25,
    "IN_PROGRESS": 40,
    "COMPLETED": 100,
}
DEFAULT_STAGE = {
    "NEW": "Создание задачи",
    "CLARIFYING": "Уточнение требований",
    "QUEUED": "Ожидание выполнения",
    "PLANNING": "Планирование",
    "IN_PROGRESS": "Выполнение через OpenClaw",
    "WAITING_APPROVAL": "Ожидание подтверждения владельца",
    "COMPLETED": "Завершено",
    "FAILED": "Ошибка выполнения",
    "CANCELLED": "Отменено владельцем",
    "EXPIRED": "Срок действия истёк",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProgressService:
    def transition(
        self,
        task: dict[str, Any],
        status: str,
        *,
        stage: str | None = None,
        progress: int | None = None,
        event: str | None = None,
    ) -> dict[str, Any]:
        if status not in VALID_STATUSES:
            raise ValueError("invalid task status")
        updated = dict(task)
        now = utc_now()
        previous_progress = int(task.get("progress", 0))
        selected_progress = DEFAULT_PROGRESS.get(status, previous_progress) if progress is None else progress
        if not isinstance(selected_progress, int) or not 0 <= selected_progress <= 100:
            raise ValueError("progress must be an integer from 0 to 100")
        updated["status"] = status
        updated["stage"] = stage or DEFAULT_STAGE[status]
        updated["progress"] = selected_progress
        updated["updated_at"] = now
        if status in TERMINAL_STATUSES:
            updated["completed_at"] = now
        else:
            updated["completed_at"] = None
        transitions = list(task.get("transitions", []))
        transitions.append(
            {
                "status": status,
                "stage": updated["stage"],
                "progress": selected_progress,
                "at": now,
                "event": event or "STATUS_CHANGED",
            }
        )
        updated["transitions"] = transitions[-100:]
        return updated
