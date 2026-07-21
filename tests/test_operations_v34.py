from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from nexora.agents.registry import AgentRegistry
from nexora.billing import BillingFoundation
from nexora.collaboration import TeamService
from nexora.database import SQLiteRepository
from nexora.integrations.telegram_runtime.services.audit_service import AuditService
from nexora.integrations.telegram_runtime.storage.audit_repository import AuditRepository
from nexora.operations import OperationsAccessDenied, OperationsService
from nexora.security.policies import PolicyEngine


PROJECT = Path(__file__).resolve().parents[1]
OWNER = "a" * 32
FOREIGN = "f" * 32


def platform(tmp_path: Path):
    database = SQLiteRepository(tmp_path / "database" / "nexora.sqlite3")
    assert database.migrate() == 11
    registry = AgentRegistry(PROJECT / "agents").load()
    audit = AuditService(AuditRepository(tmp_path / "audit"), database=database)
    policy = PolicyEngine(registry, PROJECT, status_resolver=database.agent_enabled)
    teams = TeamService(database, policy, audit)
    billing = BillingFoundation(database, audit)
    service = OperationsService(database, teams, registry, billing)
    return database, teams, service


def task(task_id: str, owner: str, *, status: str, agent: str = "research", progress: int = 40) -> dict:
    return {
        "task_id": task_id,
        "owner_namespace": owner,
        "title": f"Safe task {task_id}",
        "status": status,
        "progress": progress,
        "assigned_agent": agent,
        "created_at": "2026-07-22T08:00:00+00:00",
        "updated_at": "2026-07-22T08:01:00+00:00",
        "completed_at": "2026-07-22T08:01:00+00:00" if status in {"COMPLETED", "FAILED"} else None,
        "result_summary": "safe result",
        "error_code": "NX_PROVIDER_ERROR" if status == "FAILED" else None,
    }


def event(event_id: str, task_id: str, event_type: str, metadata: dict, timestamp: str) -> dict:
    return {
        "event_id": event_id,
        "task_id": task_id,
        "type": event_type,
        "metadata": metadata,
        "timestamp": timestamp,
    }


def test_migration_011_backup_integrity_and_reversible_schema(tmp_path: Path) -> None:
    database, teams, _ = platform(tmp_path)
    organization = teams.create_organization(OWNER, "Operations Organization")
    workspace = teams.create_workspace(OWNER, organization["id"], "Operations Workspace")
    database.add_activity({
        "id": "EVT-LEGACY-ACTIVITY", "organization_id": organization["id"],
        "workspace_id": workspace["id"], "event": "TASK_CREATED", "actor_id": database.user_id(OWNER),
        "resource_id": "NX-LEGACY", "payload": {}, "created_at": "2026-07-22T07:00:00+00:00",
    })
    backup = database.path.with_suffix(database.path.suffix + ".pre-v11.backup")
    assert backup.is_file()
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    database.rollback(11)
    assert database.schema_version() == 10
    with sqlite3.connect(database.path) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "activity_events" in names
        assert {"notifications", "agent_status_history", "dashboard_metrics"}.isdisjoint(names)
        assert connection.execute("SELECT COUNT(*) FROM activity_events").fetchone()[0] >= 1


def test_dashboard_activity_notifications_realtime_and_analytics_are_scoped(tmp_path: Path) -> None:
    database, teams, operations = platform(tmp_path)
    organization = teams.create_organization(OWNER, "Owner Organization")
    workspace = teams.create_workspace(OWNER, organization["id"], "Marketing")
    database.set_workspace_component(workspace["id"], "agent", "research", True)

    own = task("NX-OPS-001", OWNER, status="IN_PROGRESS")
    database.upsert_task(own)
    teams.link_task(OWNER, workspace["id"], own["task_id"])
    database.insert_task_event(event(
        "EVT-OPS-START", own["task_id"], "AGENT_STARTED",
        {"agent": "research", "workflow": "safe_flow", "token": "must-not-leak"}, "2026-07-22T08:00:30+00:00",
    ))
    database.insert_task_event(event(
        "EVT-OPS-STAGE", own["task_id"], "TASK_UPDATED",
        {"status": "IN_PROGRESS", "progress": 45, "stage": "Анализ данных", "authorization": "Bearer must-not-leak"},
        "2026-07-22T08:01:00+00:00",
    ))

    foreign_org = teams.create_organization(FOREIGN, "Foreign Organization")
    foreign_workspace = teams.create_workspace(FOREIGN, foreign_org["id"], "Foreign Workspace")
    foreign_task = task("NX-OPS-FOREIGN", FOREIGN, status="COMPLETED")
    database.upsert_task(foreign_task)
    teams.link_task(FOREIGN, foreign_workspace["id"], foreign_task["task_id"])

    dashboard = operations.dashboard(OWNER, workspace["id"])
    assert dashboard["workspace"] == {"id": workspace["id"], "name": "Marketing"}
    assert dashboard["active_tasks"] == 1 and dashboard["running_agents"] == 1
    assert "user_id" not in dashboard and "owner" not in dashboard

    activity = operations.activity(OWNER, workspace["id"])["items"]
    assert {item["type"] for item in activity} >= {"TASK_CREATED", "AGENT_STARTED", "TASK_UPDATED"}
    assert "must-not-leak" not in json.dumps(activity, ensure_ascii=False)

    realtime = operations.realtime_events(OWNER, workspace["id"])["items"]
    assert [item["type"] for item in realtime][-2:] == ["AGENT_STARTED", "TASK_STAGE_CHANGED"]
    assert all(item["task_id"] == own["task_id"] for item in realtime)
    after = operations.realtime_events(OWNER, workspace["id"], after_event_id="EVT-OPS-START")["items"]
    assert [item["event_id"] for item in after] == ["EVT-OPS-STAGE"]

    agents = operations.agent_status(OWNER, workspace["id"])["items"]
    assert len(agents) == 1 and agents[0]["id"] == "research"
    assert agents[0]["status"] == "RUNNING" and agents[0]["current_task"]["id"] == own["task_id"]

    analytics = operations.analytics(OWNER, workspace["id"])
    assert analytics["tasks"]["created"] == 1 and analytics["tasks"]["failed"] == 0
    assert analytics["agents"][0]["agent"] == "research"
    assert analytics["workflows"]["items"][0]["workflow"] == "safe_flow"

    with pytest.raises(OperationsAccessDenied):
        operations.dashboard(OWNER, foreign_workspace["id"])
    assert foreign_task["task_id"] not in json.dumps(activity)


def test_notification_creation_projection_read_state_and_owner_isolation(tmp_path: Path) -> None:
    database, teams, operations = platform(tmp_path)
    organization = teams.create_organization(OWNER, "Notifications Organization")
    workspace = teams.create_workspace(OWNER, organization["id"], "Notifications Workspace")
    value = task("NX-NOTIFY-001", OWNER, status="COMPLETED", progress=100)
    database.upsert_task(value)
    teams.link_task(OWNER, workspace["id"], value["task_id"])
    database.insert_task_event(event(
        "EVT-NOTIFY-COMPLETE", value["task_id"], "TASK_COMPLETED",
        {"status": "COMPLETED", "result": "token=never-return"}, "2026-07-22T09:00:00+00:00",
    ))

    values = operations.notifications(OWNER, workspace["id"])
    assert values["unread"] == 1 and values["items"][0]["type"] == "TASK_COMPLETED"
    notification = values["items"][0]
    assert "never-return" not in json.dumps(notification)
    assert operations.mark_notification_read(OWNER, notification["id"], workspace["id"])["status"] == "READ"
    assert operations.notifications(OWNER, workspace["id"], status="UNREAD")["items"] == []
    assert operations.notifications(OWNER, workspace["id"], status="READ")["items"][0]["id"] == notification["id"]

    foreign_user = database.ensure_team_user(FOREIGN, display_name="Viewer")
    database.upsert_workspace_member("MEM-OPS-VIEWER", workspace["id"], foreign_user, "VIEWER")
    database.create_notification(
        "NTF-FFFFFFFFFFFFFFFF", FOREIGN, workspace["id"], "SECURITY_ALERT", "Viewer-only alert",
    )
    foreign_notifications = operations.notifications(FOREIGN, workspace["id"])
    assert [item["id"] for item in foreign_notifications["items"]] == ["NTF-FFFFFFFFFFFFFFFF"]
    assert notification["id"] not in json.dumps(foreign_notifications)
    with pytest.raises(OperationsAccessDenied):
        operations.mark_notification_read(FOREIGN, notification["id"], workspace["id"])
