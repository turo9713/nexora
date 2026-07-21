from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from ..storage.approval_repository import ApprovalRepository
from .progress_service import utc_now


APPROVAL_TTL_MINUTES = 10


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class ApprovalService:
    def __init__(self, repository: ApprovalRepository, database: Any | None = None, event_bus: Any | None = None) -> None:
        self.repository = repository
        self.database = database
        self.event_bus = event_bus

    def _persist(self, approval: dict[str, Any]) -> None:
        if self.database is not None:
            self.database.upsert_approval(approval)

    def create(
        self,
        namespace: str,
        task_id: str,
        session_id: str,
        action_type: str,
        action_summary: str,
        risk_summary: str,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        approval = {
            "version": 1,
            "approval_id": f"APR-{secrets.token_hex(4).upper()}",
            "owner_namespace": namespace,
            "session_id": session_id,
            "task_id": task_id,
            "action_id": f"ACT-{secrets.token_hex(4).upper()}",
            "action_type": action_type[:64],
            "action_summary": " ".join(action_summary.split())[:200],
            "risk_summary": " ".join(risk_summary.split())[:300],
            "status": "PENDING",
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=APPROVAL_TTL_MINUTES)).isoformat(),
            "used_at": None,
        }
        self.repository.save(namespace, approval)
        self._persist(approval)
        if self.event_bus is not None:
            self.event_bus.publish(
                "APPROVAL_CREATED",
                task_id=task_id,
                metadata={"approval_id": approval["approval_id"], "action_type": action_type, "status": "PENDING"},
            )
        return approval

    def decide(
        self,
        namespace: str,
        approval_id: str,
        session_id: str,
        decision: str,
    ) -> tuple[str, dict[str, Any] | None]:
        approval = self.repository.get(namespace, approval_id)
        if approval is None or approval.get("session_id") != session_id:
            return "NOT_FOUND", None
        if approval.get("status") != "PENDING":
            return "ALREADY_USED", approval
        if _parse_time(str(approval["expires_at"])) <= datetime.now(timezone.utc):
            expired = dict(approval)
            expired["status"] = "EXPIRED"
            expired["used_at"] = utc_now()
            self.repository.save(namespace, expired)
            self._persist(expired)
            return "EXPIRED", expired
        if decision not in {"approve", "reject"}:
            return "INVALID", approval
        updated = dict(approval)
        updated["status"] = "APPROVED" if decision == "approve" else "REJECTED"
        updated["used_at"] = utc_now()
        self.repository.save(namespace, updated)
        self._persist(updated)
        if self.event_bus is not None:
            self.event_bus.publish(
                "APPROVAL_USED",
                task_id=str(updated["task_id"]),
                metadata={"approval_id": approval_id, "status": updated["status"]},
            )
        return updated["status"], updated

    def invalidate_task(self, namespace: str, task_id: str) -> int:
        invalidated = 0
        for approval in self.repository.list_for_task(namespace, task_id):
            if approval.get("status") != "PENDING":
                continue
            updated = dict(approval)
            updated["status"] = "INVALIDATED"
            updated["used_at"] = utc_now()
            self.repository.save(namespace, updated)
            self._persist(updated)
            invalidated += 1
        return invalidated
