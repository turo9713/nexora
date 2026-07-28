from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexora.dashboard.api import DashboardAPIError

from .conftest import NAMESPACE, PROJECT


TASK_STATUSES = (
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
)


def _task(task_id: str, owner: str, *, status: str = "IN_PROGRESS", progress: int = 47) -> dict:
    return {
        "version": 1,
        "task_id": task_id,
        "owner_namespace": owner,
        "session_id": "safe-session-reference",
        "title": f"Task {task_id}",
        "description": "Проверить безопасный read-only Task Control Center",
        "status": status,
        "stage": "Проверка результата",
        "progress": progress,
        "assigned_agent": "Content",
        "workflow": "content_factory",
        "provider_mode": "openclaw",
        "created_at": "2026-07-22T08:00:00+00:00",
        "updated_at": "2026-07-22T08:05:00+00:00",
        "completed_at": "2026-07-22T08:05:00+00:00" if status == "COMPLETED" else None,
        "result_summary": "Safe result",
        "error_code": None,
        "cancellation_requested": status == "CANCELLED",
        "pending_approval_id": None,
        "last_runtime_task_id": None,
        "turn_number": 1,
        "transitions": [],
    }


def _save(app, value: dict) -> None:
    app.api.tasks.repository.save(value["owner_namespace"], value)
    app.api.database.upsert_task(value)


def test_task_control_center_projects_runtime_fields_and_exact_progress(dashboard_factory) -> None:
    app, _ = dashboard_factory()
    value = _task("NX-CONTROL-001", NAMESPACE)
    _save(app, value)

    items = app.api.list_tasks({})["items"]
    assert len(items) == 1
    item = items[0]
    assert {
        "task_id", "title", "status", "stage", "progress", "assigned_agent",
        "workflow", "provider_mode", "created_at", "updated_at", "completed_at",
    } <= set(item)
    assert item["task_id"] == value["task_id"]
    assert item["stage"] == value["stage"]
    assert item["progress"] == 47
    assert item["assigned_agent"] == "Content"
    assert item["workflow"] == "content_factory"
    assert item["provider_mode"] == "openclaw"

    details = app.api.task_details(value["task_id"])
    assert details["description"] == value["description"]
    assert details["progress"] == 47
    assert "conversation" not in details
    assert details["downloads"][0]["id"] == "result"


@pytest.mark.parametrize("status", TASK_STATUSES)
def test_task_control_center_accepts_all_runtime_statuses(dashboard_factory, status: str) -> None:
    app, _ = dashboard_factory()
    progress = 100 if status == "COMPLETED" else 37
    value = _task(f"NX-STATUS-{status.replace('_', '-')}", NAMESPACE, status=status, progress=progress)
    _save(app, value)
    items = app.api.list_tasks({"status": status})["items"]
    assert len(items) == 1 and items[0]["status"] == status
    assert items[0]["progress"] == progress


def test_task_timeline_is_safe_ordered_and_normalizes_failed(dashboard_factory) -> None:
    app, _ = dashboard_factory()
    value = _task("NX-EVENTS-001", NAMESPACE, status="FAILED")
    _save(app, value)
    database = app.api.database
    database.insert_task_event({
        "event_id": "EVT-TASK-CREATED",
        "type": "TASK_CREATED",
        "timestamp": "2026-07-22T08:00:00+00:00",
        "task_id": value["task_id"],
        "metadata": {"status": "NEW", "progress": 0, "token": "timeline-secret-value"},
    })
    database.insert_task_event({
        "event_id": "EVT-TASK-FAILED",
        "type": "TASK_UPDATED",
        "timestamp": "2026-07-22T08:05:00+00:00",
        "task_id": value["task_id"],
        "metadata": {
            "status": "FAILED", "stage": "Provider error", "progress": 47,
            "agent": "Content", "workflow": "content_factory", "result": "FAILED",
            "authorization": "Bearer timeline-secret-value",
        },
    })

    events = app.api.task_events(value["task_id"])["items"]
    assert [item["type"] for item in events] == ["TASK_CREATED", "TASK_FAILED"]
    assert events[1] == {
        "event_id": "EVT-TASK-FAILED",
        "type": "TASK_FAILED",
        "timestamp": "2026-07-22T08:05:00+00:00",
        "status": "FAILED",
        "stage": "Provider error",
        "progress": 47,
        "agent": "Content",
        "workflow": "content_factory",
        "result": "FAILED",
    }
    serialized = json.dumps(events)
    assert "timeline-secret-value" not in serialized
    assert "authorization" not in serialized.casefold()
    assert "metadata" not in events[0]


def test_task_control_center_owner_isolation_and_safe_not_found(dashboard_factory) -> None:
    app, _ = dashboard_factory()
    own = _task("NX-OWNER-CONTROL", NAMESPACE)
    foreign = _task("NX-FOREIGN-CONTROL", "c" * 32)
    _save(app, own)
    _save(app, foreign)

    assert [item["task_id"] for item in app.api.list_tasks({})["items"]] == [own["task_id"]]
    errors = []
    for task_id in (foreign["task_id"], "NX-NOT-AVAILABLE"):
        with pytest.raises(DashboardAPIError) as denied:
            app.api.task_details(task_id)
        errors.append((denied.value.status, denied.value.code, denied.value.message))
        with pytest.raises(DashboardAPIError) as denied_events:
            app.api.task_events(task_id)
        assert (denied_events.value.status, denied_events.value.code) == (404, "TASK_NOT_FOUND")
    assert errors[0] == errors[1]


def test_task_control_center_frontend_and_http_surface_are_read_only() -> None:
    script = (PROJECT / "dashboard" / "frontend" / "app.js").read_text(encoding="utf-8")
    permissions = (PROJECT / "dashboard" / "permissions" / "service.py").read_text(encoding="utf-8")
    server = (PROJECT / "dashboard" / "backend" / "server.py").read_text(encoding="utf-8")
    assert all(status in script for status in TASK_STATUSES)
    assert all(field in script for field in (
        "task_id", "stage", "progress", "assigned_agent", "workflow", "provider_mode",
        "created_at", "updated_at", "completed_at", "/events", "Timeline",
        "Агент:", "Workflow:",
    ))
    for forbidden in ("tasksPageV31", "taskPageV31"):
        assert forbidden not in script
    assert 'api("/api/tasks",{method:"POST"' not in script
    assert 'api(`/api/tasks/${encoded}/messages`' not in script
    assert 'api(`/api/tasks/${encoded}/cancel`' not in script
    assert '"tasks:write"' not in permissions
    assert 'path == "/api/workbench/tasks"' in server
    assert 'r"/api/workbench/tasks/' in server
