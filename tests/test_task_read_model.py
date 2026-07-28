from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nexora.database import SQLiteRepository
from nexora.storage import TaskReadModel


OWNER = "a" * 32
FOREIGN_OWNER = "b" * 32


class StoredTasks:
    def __init__(self, values: dict[tuple[str, str], dict[str, Any]]) -> None:
        self.values = values
        self.lookups: list[tuple[str, str]] = []

    def get(self, owner: str, task_id: str) -> dict[str, Any] | None:
        self.lookups.append((owner, task_id))
        return self.values.get((owner, task_id))


def task(task_id: str, owner: str = OWNER, **overrides: Any) -> dict[str, Any]:
    value = {
        "task_id": task_id,
        "owner_namespace": owner,
        "title": "Read model task",
        "status": "IN_PROGRESS",
        "progress": 40,
        "assigned_agent": "Developer",
        "created_at": "2026-07-22T09:00:00+00:00",
        "updated_at": "2026-07-22T09:01:00+00:00",
        "completed_at": None,
        "result_summary": "",
        "error_code": None,
    }
    value.update(overrides)
    return value


def event(event_id: str, task_id: str, event_type: str, metadata: dict[str, Any], created_at: str) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "type": event_type,
        "task_id": task_id,
        "metadata": metadata,
        "timestamp": created_at,
    }


def repository(tmp_path: Path) -> SQLiteRepository:
    value = SQLiteRepository(tmp_path / "state" / "nexora.sqlite3")
    assert value.migrate() == 13
    return value


def test_task_dto_enriches_only_from_owner_state_and_saved_event_metadata(tmp_path: Path) -> None:
    database = repository(tmp_path)
    database.upsert_task(task("NX-READ-001", progress=140, result_summary="token=fixture-secret"))
    database.insert_task_event(
        event(
            "EVT-WORKFLOW",
            "NX-READ-001",
            "AGENT_STARTED",
            {"agent": "orchestrator", "workflow": "development_flow", "provider_mode": "openclaw"},
            "2026-07-22T09:00:02+00:00",
        )
    )
    stored = StoredTasks(
        {
            (OWNER, "NX-READ-001"): {
                "owner_namespace": OWNER,
                "task_id": "NX-READ-001",
                "stage": "Выполнение",
                "description": "Проверить проект",
            }
        }
    )
    read_model = TaskReadModel(database, stored)

    items = read_model.list(OWNER, database.list_tasks(OWNER))

    assert len(items) == 1
    value = items[0]
    assert value["id"] == value["task_id"] == "NX-READ-001"
    assert value["stage"] == "Выполнение"
    assert value["description"] == "Проверить проект"
    assert value["workflow"] == "development_flow"
    assert value["provider_mode"] == "openclaw"
    assert value["assigned_agent"] == value["agent"] == "Developer"
    assert value["progress"] == 100
    assert "fixture-secret" not in value["result_summary"]
    assert "events" not in value
    assert stored.lookups == [(OWNER, "NX-READ-001")]


def test_get_returns_sanitized_allowlisted_timeline_and_normalizes_failure(tmp_path: Path) -> None:
    database = repository(tmp_path)
    database.upsert_task(task("NX-READ-002", status="FAILED", progress=35, error_code="NX_PROVIDER_ERROR"))
    for item in (
        event("EVT-01", "NX-READ-002", "TASK_CREATED", {"status": "NEW", "progress": 0}, "2026-07-22T09:00:00+00:00"),
        event("EVT-02", "NX-READ-002", "TASK_UPDATED", {"status": "FAILED", "stage": "Authorization: Bearer event-secret", "progress": 140, "token": "drop-me"}, "2026-07-22T09:00:01+00:00"),
        event("EVT-03", "NX-READ-002", "INTERNAL_WORKER_EVENT", {"status": "FAILED"}, "2026-07-22T09:00:02+00:00"),
        event("EVT-04", "NX-READ-002", "AGENT_FINISHED", {"agent": "developer", "workflow": "development_flow", "result": "Authorization: Bearer result-secret", "approval_id": "APR-INTERNAL"}, "2026-07-22T09:00:03+00:00"),
    ):
        database.insert_task_event(item)
    read_model = TaskReadModel(database, StoredTasks({}))

    value = read_model.get(OWNER, "NX-READ-002")

    assert value is not None
    assert [item["type"] for item in value["events"]] == ["TASK_CREATED", "TASK_FAILED", "AGENT_FINISHED"]
    failed = value["events"][1]
    assert failed["status"] == "FAILED" and failed["progress"] == 100
    serialized = json.dumps(value, ensure_ascii=False)
    assert "event-secret" not in serialized and "result-secret" not in serialized
    assert "approval_id" not in serialized and "APR-INTERNAL" not in serialized
    assert set(failed) == {"event_id", "type", "timestamp", "status", "stage", "progress", "agent", "workflow", "result"}
    assert value["workflow"] == "development_flow"
    assert value["provider_mode"] is None


def test_events_are_owner_scoped_and_deterministically_ordered(tmp_path: Path) -> None:
    database = repository(tmp_path)
    database.upsert_task(task("NX-OWNER-003"))
    database.upsert_task(task("NX-FOREIGN-003", owner=FOREIGN_OWNER))
    for item in (
        event("EVT-B", "NX-OWNER-003", "TASK_UPDATED", {"status": "PLANNING"}, "2026-07-22T09:00:00+00:00"),
        event("EVT-A", "NX-OWNER-003", "TASK_CREATED", {"status": "NEW"}, "2026-07-22T09:00:00+00:00"),
        event("EVT-FOREIGN", "NX-FOREIGN-003", "TASK_CREATED", {"status": "NEW"}, "2026-07-22T09:00:00+00:00"),
    ):
        database.insert_task_event(item)
    stored = StoredTasks({})
    read_model = TaskReadModel(database, stored)

    assert [item["event_id"] for item in read_model.events(OWNER, "NX-OWNER-003")] == ["EVT-A", "EVT-B"]
    assert read_model.events(OWNER, "NX-FOREIGN-003") == []
    assert read_model.get(OWNER, "NX-FOREIGN-003") is None
    assert stored.lookups == []


def test_workspace_projection_uses_workspace_join_without_owner_json(tmp_path: Path) -> None:
    database = repository(tmp_path)
    database.upsert_task(task("NX-WORKSPACE-004"))
    organization = database.create_organization("ORG-READMODEL01", OWNER, "Read model org")
    workspace = database.create_workspace(
        "WS-READMODEL001",
        organization["id"],
        OWNER,
        "Read model workspace",
        "",
    )
    database.attach_task_workspace("NX-WORKSPACE-004", organization["id"], workspace["id"], database.user_id(OWNER) or 0)
    database.insert_task_event(
        event(
            "EVT-WS-01",
            "NX-WORKSPACE-004",
            "TASK_UPDATED",
            {"status": "IN_PROGRESS", "stage": "Workspace stage", "token": "workspace-secret"},
            "2026-07-22T09:00:04+00:00",
        )
    )
    stored = StoredTasks(
        {
            (OWNER, "NX-WORKSPACE-004"): {
                "owner_namespace": OWNER,
                "task_id": "NX-WORKSPACE-004",
                "description": "private owner context",
            }
        }
    )
    read_model = TaskReadModel(database, stored)

    value = read_model.get_workspace(workspace["id"], "NX-WORKSPACE-004")

    assert value is not None and value["stage"] == "Workspace stage"
    assert value["description"] is None
    assert "workspace-secret" not in json.dumps(value)
    assert stored.lookups == []
