"""Sanitized, owner-scoped read model for the Task Control Center."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from nexora.security.audit.redaction import redact_text, sanitize_metadata


TASK_STATUSES = {
    "NEW",
    "CLARIFYING",
    "QUEUED",
    "PLANNING",
    "IN_PROGRESS",
    "WAITING_APPROVAL",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "EXPIRED",
}

TIMELINE_EVENTS = {
    "TASK_CREATED",
    "TASK_UPDATED",
    "AGENT_STARTED",
    "AGENT_FINISHED",
    "APPROVAL_CREATED",
    "APPROVAL_USED",
    "TASK_COMPLETED",
    "TASK_FAILED",
    "TASK_CANCELLED",
}


def _text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = redact_text(value, limit).strip()
    return cleaned or None


def _task_progress(value: Any) -> int:
    try:
        selected = int(value)
    except (TypeError, ValueError, OverflowError):
        selected = 0
    return max(0, min(100, selected))


def _event_progress(value: Any) -> int | None:
    if value is None:
        return None
    try:
        selected = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return max(0, min(100, selected))


def _metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    value = row.get("payload")
    if isinstance(value, Mapping):
        parsed: Any = dict(value)
    else:
        try:
            parsed = json.loads(str(value or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = {}
    return sanitize_metadata(parsed if isinstance(parsed, dict) else {})


class TaskReadModel:
    """Build task DTOs without granting mutation or provider access."""

    def __init__(self, database: Any, tasks: Any) -> None:
        self.database = database
        self.tasks = tasks

    def list(self, owner: str, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [self._task(owner, row, include_events=False) for row in rows]

    def get(self, owner: str, task_id: str) -> dict[str, Any] | None:
        row = self.database.get_task_details(owner, task_id)
        if row is None:
            return None
        return self._task(owner, row, include_events=True)

    def events(self, owner: str, task_id: str) -> list[dict[str, Any]]:
        return self._timeline(self.database.list_task_events(owner, task_id))

    def list_workspace(self, workspace_id: str, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Project task rows after the caller has authorized the workspace."""
        return [
            self._task(
                None,
                row,
                include_events=False,
                event_rows=self.database.list_workspace_task_events(
                    workspace_id, str(row.get("id") or "")
                ),
            )
            for row in rows
        ]

    def get_workspace(self, workspace_id: str, task_id: str) -> dict[str, Any] | None:
        """Project a shared task without opening another owner's JSON state."""
        row = self.database.get_team_task(workspace_id, task_id)
        if row is None:
            return None
        event_rows = self.database.list_workspace_task_events(workspace_id, task_id)
        return self._task(None, row, include_events=True, event_rows=event_rows)

    def _timeline(self, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in rows:
            metadata = _metadata(row)
            event_type = str(row.get("event_type") or "").upper()
            status = str(metadata.get("status") or "").upper()
            if event_type == "TASK_UPDATED" and status == "FAILED":
                event_type = "TASK_FAILED"
            if event_type not in TIMELINE_EVENTS:
                continue
            result.append(
                {
                    "event_id": _text(row.get("id"), 100),
                    "type": event_type,
                    "timestamp": _text(row.get("created_at"), 64),
                    "status": status if status in TASK_STATUSES else None,
                    "stage": _text(metadata.get("stage"), 200),
                    "progress": _event_progress(metadata.get("progress")),
                    "agent": _text(metadata.get("agent"), 100),
                    "workflow": _text(metadata.get("workflow"), 100),
                    "result": _text(metadata.get("result"), 500),
                }
            )
        return result

    def _task(
        self,
        owner: str | None,
        row: Mapping[str, Any],
        *,
        include_events: bool,
        event_rows: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        task_id = _text(row.get("id") or row.get("task_id"), 100)
        stored = self._stored(owner, task_id)
        if event_rows is None:
            event_rows = self.database.list_task_events(owner, task_id) if owner and task_id else []
        timeline = self._timeline(event_rows)

        stage = self._first_text(stored, row, key="stage", limit=200)
        description = self._first_text(stored, row, key="description", limit=2000)
        workflow = self._first_text(stored, row, key="workflow", limit=100)
        provider_mode = self._first_text(stored, row, key="provider_mode", limit=100)
        if workflow is None:
            workflow = self._latest(timeline, "workflow")
        if provider_mode is None:
            provider_mode = self._latest_metadata(event_rows, "provider_mode", 100)
        if stage is None:
            stage = self._latest(timeline, "stage")

        status = str(row.get("status") or "").upper()
        assigned_agent = _text(row.get("assigned_agent") or row.get("agent"), 100)
        value: dict[str, Any] = {
            "id": task_id,
            "task_id": task_id,
            "title": _text(row.get("title"), 200),
            "description": description,
            "status": status if status in TASK_STATUSES else "UNKNOWN",
            "stage": stage,
            "progress": _task_progress(row.get("progress")),
            "assigned_agent": assigned_agent,
            "agent": assigned_agent,
            "workflow": workflow,
            "provider_mode": provider_mode,
            "created_at": _text(row.get("created_at"), 64),
            "updated_at": _text(row.get("updated_at"), 64),
            "completed_at": _text(row.get("completed_at"), 64),
            "result_summary": _text(row.get("result_summary"), 1500) or "",
            "error_code": _text(row.get("error_code"), 100),
        }
        if include_events:
            value["events"] = timeline
        return value

    def _stored(self, owner: str | None, task_id: str | None) -> Mapping[str, Any]:
        if not owner or not task_id:
            return {}
        try:
            value = self.tasks.get(owner, task_id)
        except (KeyError, OSError, RuntimeError, TypeError, ValueError):
            return {}
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _first_text(*sources: Mapping[str, Any], key: str, limit: int) -> str | None:
        for source in sources:
            value = _text(source.get(key), limit)
            if value is not None:
                return value
        return None

    @staticmethod
    def _latest(events: list[dict[str, Any]], key: str) -> str | None:
        for event in reversed(events):
            value = event.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _latest_metadata(rows: list[Mapping[str, Any]], key: str, limit: int) -> str | None:
        for row in reversed(rows):
            event_type = str(row.get("event_type") or "").upper()
            if event_type not in TIMELINE_EVENTS:
                continue
            value = _text(_metadata(row).get(key), limit)
            if value is not None:
                return value
        return None
