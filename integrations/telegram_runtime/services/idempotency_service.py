from __future__ import annotations

import secrets
from typing import Any

from ..storage.action_repository import ActionRepository
from .progress_service import utc_now


FINAL_ACTION_STATUSES = {"SUCCEEDED", "FAILED", "CANCELLED"}


class IdempotencyService:
    def __init__(self, repository: ActionRepository) -> None:
        self.repository = repository

    def begin(
        self,
        namespace: str,
        key: str,
        action_type: str,
        *,
        task_id: str | None = None,
        action_id: str | None = None,
    ) -> bool:
        existing = self.repository.get(namespace, key)
        if existing is not None and existing.get("status") in {"PENDING", "RUNNING", "SUCCEEDED"}:
            return False
        now = utc_now()
        action = {
            "version": 1,
            "action_id": action_id or f"ACT-{secrets.token_hex(4).upper()}",
            "owner_namespace": namespace,
            "task_id": task_id,
            "action_type": action_type,
            "key_hash_only": True,
            "status": "RUNNING",
            "created_at": existing.get("created_at", now) if existing else now,
            "updated_at": now,
            "completed_at": None,
        }
        self.repository.save(namespace, key, action)
        return True

    def set_status(self, namespace: str, key: str, status: str) -> None:
        if status not in {"PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"}:
            raise ValueError("invalid action status")
        action = self.repository.get(namespace, key)
        if action is None:
            return
        updated = dict(action)
        updated["status"] = status
        updated["updated_at"] = utc_now()
        if status in FINAL_ACTION_STATUSES:
            updated["completed_at"] = updated["updated_at"]
        self.repository.save(namespace, key, updated)

    def succeeded(self, namespace: str, key: str) -> bool:
        action = self.repository.get(namespace, key)
        return bool(action and action.get("status") == "SUCCEEDED")
