from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Any

from nexora.storage.document_artifacts import ARCHIVE_HINTS, SPREADSHEET_HINTS

from ..storage.task_repository import TaskRepository
from .progress_service import ProgressService, TERMINAL_STATUSES, utc_now


SAFE_ERROR_CODES = {
    "NX_TIMEOUT",
    "NX_PROVIDER_ERROR",
    "NX_VALIDATION_ERROR",
    "NX_PERMISSION_DENIED",
    "NX_TASK_NOT_FOUND",
    "NX_TASK_CANCELLED",
    "NX_APPROVAL_EXPIRED",
    "NX_WORKSPACE_REQUIRED",
    "NX_INTERNAL_ERROR",
}


def _clean_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())[:limit]


def _task_title(value: Any, limit: int = 100) -> str:
    """Keep a short title without losing explicit rich-artifact requirements."""

    normalized = " ".join(str(value or "").replace("\x00", "").split())
    folded = normalized.casefold()
    markers = []
    if any(hint in folded for hint in SPREADSHEET_HINTS):
        markers.append("[XLSX]")
    if any(hint in folded for hint in ARCHIVE_HINTS):
        markers.append("[ZIP]")
    suffix = f" {' '.join(markers)}" if markers else ""
    base = normalized[: max(0, limit - len(suffix))].rstrip()
    return f"{base}{suffix}"[:limit]


class TaskService:
    def __init__(
        self,
        repository: TaskRepository,
        progress: ProgressService | None = None,
        database: Any | None = None,
        event_bus: Any | None = None,
    ) -> None:
        self.repository = repository
        self.progress = progress or ProgressService()
        self.database = database
        self.event_bus = event_bus

    def _persist_platform(self, task: dict[str, Any]) -> None:
        if self.database is not None:
            self.database.upsert_task(task)

    def _event(self, event_type: str, task: dict[str, Any], **metadata: Any) -> None:
        if self.event_bus is not None:
            if task.get("workspace_id"):
                metadata["workspace_id"] = task["workspace_id"]
            self.event_bus.publish(event_type, task_id=str(task["task_id"]), metadata=metadata)

    def new_task_id(self) -> str:
        date = datetime.now(timezone.utc).strftime("%Y%m%d")
        suffix = secrets.token_hex(3).upper()
        return f"NX-{date}-{suffix}"

    def create(
        self,
        namespace: str,
        title: str,
        session_id: str,
        task_id: str | None = None,
        *,
        workspace_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_id = task_id or self.new_task_id()
        now = utc_now()
        task = {
            "version": 1,
            "task_id": task_id,
            "owner_namespace": namespace,
            "session_id": session_id,
            "title": _task_title(title, 100) or "Новая задача",
            "status": "NEW",
            "stage": "Создание задачи",
            "progress": 0,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "assigned_agent": "Developer",
            "result_summary": "",
            "error_code": None,
            "cancellation_requested": False,
            "pending_approval_id": None,
            "last_runtime_task_id": None,
            "turn_number": 0,
            "transitions": [
                {"status": "NEW", "stage": "Создание задачи", "progress": 0, "at": now, "event": "CREATED"}
            ],
        }
        if workspace_context is not None:
            task.update(
                organization_id=str(workspace_context["organization_id"]),
                workspace_id=str(workspace_context["workspace_id"]),
                creator_id=int(workspace_context["user_id"]),
                assignee_id=None,
            )
        self.repository.save(namespace, task)
        self._persist_platform(task)
        self._event("TASK_CREATED", task, status="NEW", progress=0, agent=task["assigned_agent"])
        return task

    def bind_workspace(
        self,
        namespace: str,
        task_id: str,
        workspace_context: dict[str, Any],
    ) -> dict[str, Any]:
        task = self.get(namespace, task_id)
        if task is None:
            raise KeyError("task not found")
        selected = str(workspace_context["workspace_id"])
        existing = task.get("workspace_id")
        if existing and existing != selected:
            raise PermissionError("task workspace mismatch")
        updated = dict(task)
        updated.update(
            organization_id=str(workspace_context["organization_id"]),
            workspace_id=selected,
            creator_id=int(workspace_context["user_id"]),
            assignee_id=task.get("assignee_id"),
        )
        self.repository.save(namespace, updated)
        self._persist_platform(updated)
        return updated

    def get(self, namespace: str, task_id: str) -> dict[str, Any] | None:
        return self.repository.get(namespace, task_id)

    def transition(self, namespace: str, task_id: str, status: str, **kwargs: Any) -> dict[str, Any]:
        task = self.get(namespace, task_id)
        if task is None:
            raise KeyError("task not found")
        if task.get("cancellation_requested") and status != "CANCELLED":
            return task
        updated = self.progress.transition(task, status, **kwargs)
        self.repository.save(namespace, updated)
        self._persist_platform(updated)
        event_type = "TASK_UPDATED"
        if status == "COMPLETED":
            event_type = "TASK_COMPLETED"
        elif status == "CANCELLED":
            event_type = "TASK_CANCELLED"
        self._event(event_type, updated, status=status, progress=updated.get("progress"), stage=updated.get("stage"))
        return updated

    def update_fields(self, namespace: str, task_id: str, **fields: Any) -> dict[str, Any]:
        task = self.get(namespace, task_id)
        if task is None:
            raise KeyError("task not found")
        updated = dict(task)
        allowed = {
            "result_summary",
            "error_code",
            "cancellation_requested",
            "pending_approval_id",
            "last_runtime_task_id",
            "turn_number",
            "assigned_agent",
        }
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError("unsupported task field")
            if key == "result_summary":
                value = _clean_text(value, 1500)
            if key == "error_code" and value is not None and value not in SAFE_ERROR_CODES:
                raise ValueError("unsafe error code")
            updated[key] = value
        updated["updated_at"] = utc_now()
        self.repository.save(namespace, updated)
        self._persist_platform(updated)
        return updated

    def history(self, namespace: str, limit: int) -> list[dict[str, Any]]:
        return self.repository.list(namespace, limit)

    def import_legacy(self, namespace: str, legacy: dict[str, Any]) -> dict[str, Any] | None:
        task_id = str(legacy.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9-]{3,100}", task_id) or self.get(namespace, task_id) is not None:
            return None
        raw_status = str(legacy.get("status") or "FAILED")
        status = raw_status if raw_status in {"COMPLETED", "FAILED", "CANCELLED"} else "COMPLETED"
        created = str(legacy.get("created_at") or utc_now())
        updated_at = str(legacy.get("updated_at") or created)
        task = {
            "version": 1,
            "task_id": task_id,
            "owner_namespace": namespace,
            "session_id": "legacy-v1.3",
            "title": _clean_text(legacy.get("title") or legacy.get("description"), 100) or "Legacy task",
            "status": status,
            "stage": f"Импортировано из v1.3: {status}",
            "progress": 100 if status == "COMPLETED" else 0,
            "created_at": created,
            "updated_at": updated_at,
            "completed_at": updated_at if status in TERMINAL_STATUSES else None,
            "assigned_agent": _clean_text(legacy.get("assigned_agent"), 80) or "Developer",
            "result_summary": "Результат сохранён в совместимом хранилище v1.3.",
            "error_code": None,
            "cancellation_requested": status == "CANCELLED",
            "pending_approval_id": None,
            "last_runtime_task_id": task_id,
            "turn_number": 1,
            "transitions": [
                {"status": status, "stage": "Импортировано из v1.3", "progress": 100 if status == "COMPLETED" else 0, "at": updated_at, "event": "MIGRATED"}
            ],
        }
        self.repository.save(namespace, task)
        self._persist_platform(task)
        return task
