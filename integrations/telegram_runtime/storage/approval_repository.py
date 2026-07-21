from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json, ensure_secure_directory, read_json
from .task_repository import NAMESPACE_PATTERN


APPROVAL_ID_PATTERN = re.compile(r"^APR-[A-Z0-9]{8}$")


class ApprovalRepository:
    def __init__(self, root: Path) -> None:
        root = Path(root)
        ensure_secure_directory(root.parent)
        self.root = ensure_secure_directory(root)

    def _namespace_dir(self, namespace: str) -> Path:
        if not NAMESPACE_PATTERN.fullmatch(namespace):
            raise ValueError("invalid owner namespace")
        return ensure_secure_directory(self.root / namespace)

    def _path(self, namespace: str, approval_id: str) -> Path:
        if not APPROVAL_ID_PATTERN.fullmatch(approval_id):
            raise ValueError("invalid approval id")
        return self._namespace_dir(namespace) / f"{approval_id}.json"

    def save(self, namespace: str, approval: dict[str, Any]) -> None:
        if approval.get("owner_namespace") != namespace:
            raise PermissionError("approval namespace mismatch")
        atomic_write_json(self._path(namespace, str(approval["approval_id"])), approval)

    def get(self, namespace: str, approval_id: str) -> dict[str, Any] | None:
        try:
            value = read_json(self._path(namespace, approval_id))
        except (ValueError, RuntimeError):
            return None
        if not isinstance(value, dict) or value.get("owner_namespace") != namespace:
            return None
        return value

    def list_for_task(self, namespace: str, task_id: str) -> list[dict[str, Any]]:
        approvals: list[dict[str, Any]] = []
        for path in self._namespace_dir(namespace).glob("APR-*.json"):
            value = read_json(path)
            if isinstance(value, dict) and value.get("task_id") == task_id and value.get("owner_namespace") == namespace:
                approvals.append(value)
        return approvals

    def list(self, namespace: str, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        approvals: list[dict[str, Any]] = []
        for path in self._namespace_dir(namespace).glob("APR-*.json"):
            value = read_json(path)
            if not isinstance(value, dict) or value.get("owner_namespace") != namespace:
                continue
            if status and value.get("status") != status:
                continue
            approvals.append(value)
        approvals.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return approvals[: max(1, min(200, int(limit)))]
