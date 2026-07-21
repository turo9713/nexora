"""Approval gating for Nexora runtime."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from uuid import uuid4


class ApprovalManager:
    def __init__(self, validators):
        self.validators = validators
        self.pending = {}

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_pending(self, task: dict, requested_agent: str) -> dict:
        approval = {
            "approval_id": str(uuid4()),
            "task_id": task["id"],
            "requested_by": task["created_by"],
            "requested_action": requested_agent,
            "description": task["description"],
            "risk_level": "LOW",
            "created_at": self._now(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
            "status": "PENDING",
            "approved_by": None,
            "approved_at": None,
        }
        self.validators.validate_approval(approval)
        self.pending[approval["approval_id"]] = approval
        return approval

    def is_required(self, task: dict) -> bool:
        return bool(task.get("approval_required", False))

    def status(self, approval_id: str) -> dict:
        return self.pending.get(approval_id, {"status": "UNKNOWN"})
