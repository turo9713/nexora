"""User-facing operations read layer for Nexora v3.4."""

from __future__ import annotations

import json
import secrets
from collections import Counter
from typing import Any

from nexora.collaboration import TeamAccessDenied
from nexora.security.audit.redaction import redact_text, sanitize_metadata

from .realtime import RealtimeService


ACTIVITY_EVENTS = {
    "TASK_CREATED",
    "TASK_UPDATED",
    "TASK_STARTED",
    "TASK_PROGRESS_UPDATED",
    "TASK_STAGE_CHANGED",
    "AGENT_STARTED",
    "AGENT_FINISHED",
    "TASK_COMPLETED",
    "TASK_FAILED",
    "TASK_CANCELLED",
    "APPROVAL_CREATED",
    "APPROVAL_USED",
    "COMMENT_ADDED",
    "USER_JOINED",
}
NOTIFICATION_TYPES = {"TASK_COMPLETED", "TASK_FAILED", "APPROVAL_REQUIRED", "AGENT_ERROR", "SECURITY_ALERT"}


def _text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    selected = redact_text(value, limit).strip()
    return selected or None


class OperationsAccessDenied(PermissionError):
    pass


class OperationsValidationError(ValueError):
    pass


class OperationsService:
    """Deny-by-default facade for Dashboard/API operational projections."""

    def __init__(self, database: Any, teams: Any, registry: Any, billing: Any | None = None) -> None:
        self.database = database
        self.teams = teams
        self.registry = registry
        self.billing = billing
        self.realtime = RealtimeService(database)

    def dashboard(self, actor: str, requested_workspace: str | None = None) -> dict[str, Any]:
        workspace_id, context = self._workspace(actor, requested_workspace)
        values = self.database.operations_dashboard(actor, workspace_id)
        usage_percent = self._usage_percent(actor, str(context["organization_id"]))
        return {
            "welcome": "Добро пожаловать в Nexora",
            "workspace": {"id": workspace_id, "name": values.get("workspace_name") or "Workspace"},
            "active_tasks": values["active_tasks"],
            "completed_tasks": values["completed_tasks"],
            "running_agents": values["running_agents"],
            "pending_approvals": values["pending_approvals"],
            "unread_notifications": values["unread_notifications"],
            "usage_percent": usage_percent,
            "realtime_cursor": values["realtime_cursor"],
            "onboarding": {
                "completed": int(values["tasks_total"]) > 0,
                "steps": ["Выбрать workspace", "Выбрать шаблон", "Создать первую задачу", "Проверить результат"],
            },
        }

    def workspace_overview(self, actor: str, requested_workspace: str | None = None) -> dict[str, Any]:
        workspace_id, context = self._workspace(actor, requested_workspace)
        values = self.database.operations_dashboard(actor, workspace_id)
        return {
            "id": workspace_id,
            "name": values.get("workspace_name") or "Workspace",
            "organization_id": context["organization_id"],
            "role": context["role"],
            "members": values["members"],
            "agents": values["agents"],
            "tasks": values["tasks_total"],
            "skills": values["skills"],
            "usage_percent": self._usage_percent(actor, str(context["organization_id"])),
        }

    def activity(
        self,
        actor: str,
        requested_workspace: str | None = None,
        *,
        limit: int = 50,
    ) -> dict[str, Any]:
        workspace_id, _ = self._workspace(actor, requested_workspace, "audit:read")
        selected_limit = max(1, min(100, int(limit)))
        items: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for row in self.database.list_operations_activity(workspace_id, selected_limit * 2):
            projected = self._activity(row)
            if projected is None:
                continue
            identity = (projected["type"], projected.get("resource_id") or "", projected["timestamp"])
            if identity in seen:
                continue
            seen.add(identity)
            items.append(projected)
            if len(items) >= selected_limit:
                break
        return {"workspace_id": workspace_id, "items": items}

    def notifications(
        self,
        actor: str,
        requested_workspace: str | None = None,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        workspace_id, _ = self._workspace(actor, requested_workspace)
        normalized = str(status or "").upper() or None
        if normalized not in {None, "UNREAD", "READ"}:
            raise OperationsValidationError("invalid notification status")
        rows = self.database.list_notifications(
            actor, workspace_id, status=normalized, limit=max(1, min(100, int(limit))),
        )
        return {
            "workspace_id": workspace_id,
            "unread": sum(1 for item in self.database.list_notifications(actor, workspace_id, status="UNREAD", limit=200)),
            "items": [self._notification(item) for item in rows],
        }

    def mark_notification_read(self, actor: str, notification_id: str, requested_workspace: str | None = None) -> dict[str, Any]:
        workspace_id, _ = self._workspace(actor, requested_workspace)
        if not self.database.mark_notification_read(actor, workspace_id, str(notification_id)[:100]):
            raise OperationsAccessDenied("notification unavailable")
        return {"id": str(notification_id)[:100], "status": "READ"}

    def create_notification(self, actor: str, workspace_id: str, notification_type: str, message: str) -> dict[str, Any]:
        self._workspace(actor, workspace_id)
        selected_type = str(notification_type).upper()
        if selected_type not in NOTIFICATION_TYPES:
            raise OperationsValidationError("unsupported notification type")
        clean = redact_text(message, 500).strip()
        if not clean:
            raise OperationsValidationError("empty notification")
        return self.database.create_notification(
            "NTF-" + secrets.token_hex(8).upper(), actor, workspace_id, selected_type, clean,
        )

    def agent_status(self, actor: str, requested_workspace: str | None = None) -> dict[str, Any]:
        workspace_id, _ = self._workspace(actor, requested_workspace)
        configured = set(self.database.list_workspace_components(workspace_id, "agent"))
        items = []
        for manifest in self.registry.all():
            if configured and manifest.id not in configured:
                continue
            override = self.database.get_agent_override(manifest.id)
            enabled = manifest.enabled if override is None else override
            summary = self.database.agent_operational_summary(workspace_id, manifest.id)
            active = summary.get("active_task")
            latest = summary.get("latest_task")
            history = summary.get("history")
            if not enabled:
                status, health = "DISABLED", "UNKNOWN"
            elif active:
                status, health = "RUNNING", "GOOD"
            elif history and history.get("status") == "ERROR" and latest and latest.get("status") == "FAILED":
                status, health = "ERROR", "DEGRADED"
            else:
                status, health = ("IDLE", "GOOD") if latest else ("READY", "GOOD")
            items.append({
                "id": manifest.id,
                "name": manifest.name,
                "status": status,
                "health": health,
                "current_task": None if active is None else {
                    "id": _text(active.get("id"), 100),
                    "title": _text(active.get("title"), 200),
                },
                "last_execution": None if latest is None else _text(latest.get("updated_at"), 64),
                "error_code": None if latest is None else _text(latest.get("error_code"), 100),
            })
        return {"workspace_id": workspace_id, "items": items}

    def analytics(self, actor: str, requested_workspace: str | None = None) -> dict[str, Any]:
        workspace_id, _ = self._workspace(actor, requested_workspace)
        value = self.database.operations_analytics(workspace_id)
        tasks = value["tasks"]
        created = int(tasks.get("created") or 0)
        completed = int(tasks.get("completed") or 0)
        failed = int(tasks.get("failed") or 0)
        average = round(float(tasks.get("average_seconds") or 0.0), 1)
        agents = []
        for item in value["agents"]:
            executions = int(item.get("executions") or 0)
            successes = int(item.get("completed") or 0)
            errors = int(item.get("errors") or 0)
            terminal = successes + errors
            agents.append({
                "agent": _text(item.get("agent"), 100),
                "executions": executions,
                "success_rate": round((successes / terminal * 100), 1) if terminal else 0.0,
                "errors": errors,
            })
        stages = Counter()
        task_workflows: dict[str, tuple[str, str]] = {}
        for item in self.database.list_operations_activity(workspace_id, 200):
            try:
                payload = json.loads(str(item.get("payload") or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            stage = _text(sanitize_metadata(payload).get("stage"), 100)
            if stage:
                stages[stage] += 1
        for item in value.get("workflow_events", []):
            try:
                payload = json.loads(str(item.get("payload") or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            workflow = _text(sanitize_metadata(payload).get("workflow"), 100)
            task_id = _text(item.get("task_id"), 100)
            status = _text(item.get("status"), 40)
            if workflow and task_id and status:
                task_workflows[task_id] = (workflow, status.upper())
        workflow_totals: dict[str, Counter[str]] = {}
        for workflow, status in task_workflows.values():
            bucket = workflow_totals.setdefault(workflow, Counter())
            bucket["executions"] += 1
            if status == "COMPLETED":
                bucket["completed"] += 1
            elif status == "FAILED":
                bucket["failed"] += 1
        workflows = []
        for workflow, bucket in sorted(workflow_totals.items()):
            terminal = bucket["completed"] + bucket["failed"]
            workflows.append({
                "workflow": workflow,
                "executions": bucket["executions"],
                "success_rate": round((bucket["completed"] / terminal * 100), 1) if terminal else 0.0,
                "errors": bucket["failed"],
            })
        terminal_tasks = completed + failed
        return {
            "workspace_id": workspace_id,
            "tasks": {
                "created": created,
                "completed": completed,
                "failed": failed,
                "success_rate": round((completed / terminal_tasks * 100), 1) if terminal_tasks else 0.0,
                "average_duration_seconds": average,
            },
            "agents": agents,
            "workflows": {
                "items": workflows,
                "bottlenecks": [{"stage": stage, "events": count} for stage, count in stages.most_common(5)],
            },
        }

    def realtime_events(
        self,
        actor: str,
        requested_workspace: str | None = None,
        *,
        after_event_id: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        workspace_id, _ = self._workspace(actor, requested_workspace)
        items = self.realtime.read(workspace_id, after_event_id=after_event_id, limit=limit)
        return {"workspace_id": workspace_id, "items": items}

    def _workspace(self, actor: str, requested: str | None, permission: str = "tasks:read") -> tuple[str, dict[str, Any]]:
        try:
            if requested:
                workspace_id = str(requested)
            else:
                workspaces = self.teams.list_workspaces(actor)
                if not workspaces:
                    raise OperationsAccessDenied("workspace unavailable")
                workspace_id = str(workspaces[0]["id"])
            context = self.teams.workspace_context(actor, workspace_id, permission)
            return workspace_id, context
        except TeamAccessDenied as exc:
            raise OperationsAccessDenied("workspace unavailable") from exc

    def _usage_percent(self, actor: str, organization_id: str) -> int:
        if self.billing is None:
            return 0
        try:
            values = self.billing.limits(actor, organization_id)
            current = values.get("current", {})
            limits = values.get("limits", {})
            selected = limits.get("tasks_monthly")
            if selected in {None, 0}:
                return 0
            return max(0, min(100, round(int(current.get("tasks_monthly") or 0) / int(selected) * 100)))
        except (KeyError, TypeError, ValueError, PermissionError):
            return 0

    @staticmethod
    def _activity(row: dict[str, Any]) -> dict[str, Any] | None:
        event_type = str(row.get("event") or "").upper()
        try:
            payload = json.loads(str(row.get("payload") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        safe = sanitize_metadata(payload if isinstance(payload, dict) else {})
        status = str(safe.get("status") or "").upper()
        if event_type == "TASK_UPDATED" and status == "FAILED":
            event_type = "TASK_FAILED"
        if event_type not in ACTIVITY_EVENTS:
            return None
        labels = {
            "TASK_CREATED": "Задача создана",
            "TASK_UPDATED": "Задача обновлена",
            "TASK_STARTED": "Задача запущена",
            "TASK_PROGRESS_UPDATED": "Прогресс задачи обновлён",
            "TASK_STAGE_CHANGED": "Этап задачи изменён",
            "AGENT_STARTED": "Агент запущен",
            "AGENT_FINISHED": "Агент завершил работу",
            "TASK_COMPLETED": "Задача завершена",
            "TASK_FAILED": "Задача завершилась с ошибкой",
            "TASK_CANCELLED": "Задача отменена",
            "APPROVAL_CREATED": "Требуется подтверждение",
            "APPROVAL_USED": "Подтверждение использовано",
            "COMMENT_ADDED": "Добавлен комментарий",
            "USER_JOINED": "Участник присоединился",
        }
        return {
            "id": _text(row.get("id"), 120),
            "type": event_type,
            "message": labels[event_type],
            "resource_id": _text(row.get("resource_id"), 100),
            "stage": _text(safe.get("stage"), 120),
            "progress": RealtimeService._progress(safe.get("progress")) if "progress" in safe else None,
            "timestamp": _text(row.get("created_at"), 64),
        }

    @staticmethod
    def _notification(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": _text(item.get("id"), 100),
            "type": str(item.get("type") or "") if str(item.get("type") or "") in NOTIFICATION_TYPES else "SECURITY_ALERT",
            "message": _text(item.get("message"), 500) or "Уведомление Nexora",
            "status": "READ" if item.get("status") == "READ" else "UNREAD",
            "created_at": _text(item.get("created_at"), 64),
            "read_at": _text(item.get("read_at"), 64),
        }
