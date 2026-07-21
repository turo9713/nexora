from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json, ensure_secure_directory, read_json
from .task_repository import NAMESPACE_PATTERN


class ActionRepository:
    def __init__(self, root: Path) -> None:
        root = Path(root)
        ensure_secure_directory(root.parent)
        self.root = ensure_secure_directory(root)

    def _namespace_dir(self, namespace: str) -> Path:
        if not NAMESPACE_PATTERN.fullmatch(namespace):
            raise ValueError("invalid owner namespace")
        return ensure_secure_directory(self.root / namespace)

    def _path(self, namespace: str, idempotency_key: str) -> Path:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return self._namespace_dir(namespace) / f"{digest}.json"

    def get(self, namespace: str, idempotency_key: str) -> dict[str, Any] | None:
        value = read_json(self._path(namespace, idempotency_key))
        return value if isinstance(value, dict) else None

    def save(self, namespace: str, idempotency_key: str, action: dict[str, Any]) -> None:
        if action.get("owner_namespace") != namespace:
            raise PermissionError("action namespace mismatch")
        atomic_write_json(self._path(namespace, idempotency_key), action)
