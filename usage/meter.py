from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any


class UsageError(ValueError):
    pass


USAGE_METRICS = {
    "tasks_created", "tasks_completed", "tasks_failed", "agent_runs", "skill_runs",
    "workflow_duration_ms", "files", "documents", "knowledge_size_bytes",
}
TRUSTED_SOURCES = {"task_runtime", "workflow_runtime", "knowledge_service", "cloud_manager", "migration"}


class UsageMeter:
    def __init__(self, database: Any, audit: Any) -> None:
        self.database = database
        self.audit = audit

    def record(self, organization_id: str, workspace_id: str | None, metric: str, value: int, *, source: str) -> dict[str, Any]:
        if metric not in USAGE_METRICS or source not in TRUSTED_SOURCES or not isinstance(value, int) or value < 0:
            raise UsageError("invalid usage event")
        organization = self.database.get_organization(organization_id)
        if organization is None:
            raise UsageError("organization unavailable")
        if workspace_id:
            workspace = self.database.get_workspace(workspace_id)
            if workspace is None or workspace["organization_id"] != organization_id:
                raise UsageError("workspace unavailable")
        event = {
            "id": "USE-" + secrets.token_hex(8).upper(), "organization_id": organization_id,
            "workspace_id": workspace_id, "metric": metric, "value": value, "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.database.insert_usage_event(event)
        self.audit.record("USAGE_RECORDED", source="usage_meter", action_result="SUCCESS", organization_id=organization_id, workspace_id=workspace_id, metric=metric, value=value)
        return {key: event[key] for key in ("id", "organization_id", "workspace_id", "metric", "value", "timestamp")}

    def summary(self, organization_id: str) -> dict[str, Any]:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        return {"month": month, "events": self.database.usage_summary(organization_id, month), "resources": self.database.organization_resource_usage(organization_id, month)}
