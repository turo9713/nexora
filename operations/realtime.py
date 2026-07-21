"""Tenant-scoped realtime read projection for Dashboard Server-Sent Events."""

from __future__ import annotations

import json
from typing import Any

from nexora.security.audit.redaction import redact_text, sanitize_metadata


REALTIME_EVENT_TYPES = {
    "TASK_CREATED",
    "TASK_STARTED",
    "TASK_PROGRESS_UPDATED",
    "TASK_STAGE_CHANGED",
    "AGENT_STARTED",
    "AGENT_FINISHED",
    "TASK_COMPLETED",
    "TASK_FAILED",
}


def _text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    selected = redact_text(value, limit).strip()
    return selected or None


class RealtimeService:
    """Read the durable Event Bus journal and emit only safe UI events."""

    def __init__(self, database: Any) -> None:
        self.database = database

    def read(self, workspace_id: str, *, after_event_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.database.list_realtime_task_events(
            workspace_id,
            after_event_id=self._cursor(after_event_id),
            limit=limit,
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            event = self._project(row)
            if event is not None:
                result.append(event)
        return result

    @staticmethod
    def encode(event: dict[str, Any]) -> bytes:
        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        return f"id: {event['event_id']}\nevent: {event['type']}\ndata: {payload}\n\n".encode("utf-8")

    @staticmethod
    def _cursor(value: str | None) -> str | None:
        selected = str(value or "")[:120]
        return selected or None

    @staticmethod
    def _project(row: dict[str, Any]) -> dict[str, Any] | None:
        try:
            raw = json.loads(str(row.get("payload") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            raw = {}
        metadata = sanitize_metadata(raw if isinstance(raw, dict) else {})
        raw_type = str(row.get("event_type") or "").upper()
        status = str(metadata.get("status") or row.get("status") or "").upper()
        progress = RealtimeService._progress(metadata.get("progress", row.get("progress")))
        stage = _text(metadata.get("stage"), 160)
        event_type = raw_type
        if raw_type == "TASK_UPDATED":
            if status == "FAILED":
                event_type = "TASK_FAILED"
            elif status == "IN_PROGRESS" and progress <= 30:
                event_type = "TASK_STARTED"
            elif stage:
                event_type = "TASK_STAGE_CHANGED"
            else:
                event_type = "TASK_PROGRESS_UPDATED"
        if event_type not in REALTIME_EVENT_TYPES:
            return None
        return {
            "event_id": _text(row.get("id"), 120),
            "type": event_type,
            "timestamp": _text(row.get("created_at"), 64),
            "task_id": _text(row.get("task_id"), 100),
            "status": status[:40] or None,
            "stage": stage,
            "progress": progress,
            "agent": _text(metadata.get("agent") or row.get("agent"), 100),
            "error_code": _text(row.get("error_code"), 100),
        }

    @staticmethod
    def _progress(value: Any) -> int:
        try:
            progress = int(value)
        except (TypeError, ValueError, OverflowError):
            progress = 0
        return max(0, min(100, progress))
