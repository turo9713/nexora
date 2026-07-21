from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json, ensure_secure_directory, read_json


NAMESPACE_PATTERN = re.compile(r"^[a-f0-9]{32,64}$")
TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{3,100}$")


class TaskRepository:
    def __init__(self, root: Path) -> None:
        root = Path(root)
        ensure_secure_directory(root.parent)
        self.root = ensure_secure_directory(root)

    def _namespace_dir(self, namespace: str) -> Path:
        if not NAMESPACE_PATTERN.fullmatch(namespace):
            raise ValueError("invalid owner namespace")
        return ensure_secure_directory(self.root / namespace)

    def _path(self, namespace: str, task_id: str) -> Path:
        if not TASK_ID_PATTERN.fullmatch(task_id):
            raise ValueError("invalid task id")
        return self._namespace_dir(namespace) / f"{task_id}.json"

    def save(self, namespace: str, task: dict[str, Any]) -> None:
        if task.get("owner_namespace") != namespace:
            raise PermissionError("task namespace mismatch")
        atomic_write_json(self._path(namespace, str(task["task_id"])), task)

    def get(self, namespace: str, task_id: str) -> dict[str, Any] | None:
        try:
            value = read_json(self._path(namespace, task_id))
        except (ValueError, RuntimeError):
            return None
        if not isinstance(value, dict) or value.get("owner_namespace") != namespace:
            return None
        return value

    def list(self, namespace: str, limit: int = 20) -> list[dict[str, Any]]:
        directory = self._namespace_dir(namespace)
        tasks: list[dict[str, Any]] = []
        for path in directory.glob("*.json"):
            value = read_json(path)
            if isinstance(value, dict) and value.get("owner_namespace") == namespace:
                tasks.append(value)
        tasks.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        return tasks[: max(0, limit)]
