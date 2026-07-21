from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from nexora.security.audit.redaction import sanitize_metadata


EVENT_TYPES = {
    "TASK_CREATED",
    "TASK_UPDATED",
    "TASK_CANCELLED",
    "TASK_COMPLETED",
    "APPROVAL_CREATED",
    "APPROVAL_USED",
    "AGENT_STARTED",
    "AGENT_FINISHED",
    "SECURITY_DENIED",
    "SKILL_REGISTERED",
    "SKILL_VALIDATED",
    "SKILL_ENABLED",
    "SKILL_DISABLED",
    "SKILL_FAILED",
    "SKILL_REMOVED",
}

EventSink = Callable[[dict[str, Any]], None]


class EventBus:
    """Small synchronous event bus with sanitized, bounded payloads."""

    def __init__(self, sinks: list[EventSink] | None = None) -> None:
        self._sinks = list(sinks or [])
        self.last_errors: list[str] = []

    def subscribe(self, sink: EventSink) -> None:
        self._sinks.append(sink)

    def publish(self, event_type: str, *, task_id: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        if event_type not in EVENT_TYPES:
            raise ValueError("unsupported event type")
        event = {
            "event_id": f"EVT-{uuid4().hex.upper()}",
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_id": str(task_id)[:100] if task_id else None,
            "metadata": sanitize_metadata(metadata or {}),
        }
        self.last_errors.clear()
        for sink in tuple(self._sinks):
            try:
                sink(event)
            except Exception as exc:  # audit failure must not repeat the requested action
                self.last_errors.append(type(exc).__name__)
        return event


class SQLiteEventSink:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def __call__(self, event: dict[str, Any]) -> None:
        self.repository.insert_task_event(event)
