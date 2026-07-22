"""Task lifecycle management for Nexora runtime."""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

from nexora.storage.secure_io import ensure_private_directory, secure_atomic_write_json


class TaskManager:
    def __init__(self, validators):
        self.validators = validators
        self.tasks_dir = Path("/workspace/nexora/runtime/state/tasks")
        ensure_private_directory(self.tasks_dir)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _history_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.history.json"

    def _append_history(self, task: dict, event: str, **extra) -> None:
        history = []
        path = self._history_path(task["id"])
        if path.exists():
            history = json.loads(path.read_text(encoding="utf-8"))
        history.append({"event": event, "at": self._now(), **extra})
        secure_atomic_write_json(path, history, root=self.tasks_dir)

    def create_task(self, task_data: dict) -> dict:
        task = {
            "id": task_data["id"],
            "title": task_data["title"],
            "description": task_data["description"],
            "created_by": task_data["created_by"],
            "created_at": task_data.get("created_at", self._now()),
            "updated_at": task_data.get("updated_at", self._now()),
            "priority": task_data.get("priority", "NORMAL"),
            "status": task_data.get("status", "CREATED"),
            "assigned_agent": task_data.get("assigned_agent", "orchestrator"),
            "workflow": task_data.get("workflow", "default"),
            "parent_task_id": task_data.get("parent_task_id"),
            "context": task_data.get("context", {}),
            "result_reference": task_data.get("result_reference"),
            "approval_required": bool(task_data.get("approval_required", False)),
        }
        self.validators.validate_task(task)
        self._save(task)
        self._append_history(task, "CREATED", status=task["status"])
        return task

    def update_status(self, task_id: str, status: str, **extra) -> dict:
        task = self._load(task_id)
        task["status"] = status
        task["updated_at"] = self._now()
        task.update(extra)
        self.validators.validate_task(task)
        self._save(task)
        self._append_history(task, "STATUS_UPDATED", status=status, extra=extra)
        return task

    def complete_task(self, task_id: str, result: dict) -> dict:
        task = self._load(task_id)
        task["status"] = "COMPLETED"
        task["updated_at"] = self._now()
        task["result_reference"] = result["result_id"]
        self.validators.validate_task(task)
        self._save(task)
        self._append_history(task, "COMPLETED", result_reference=result["result_id"])
        return task

    def _path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.json"

    def _save(self, task: dict) -> None:
        secure_atomic_write_json(self._path(task["id"]), task, root=self.tasks_dir)

    def _load(self, task_id: str) -> dict:
        return json.loads(self._path(task_id).read_text(encoding="utf-8"))
