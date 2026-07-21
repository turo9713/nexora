from __future__ import annotations

import pytest

from nexora.agents.registry import REQUIRED_AGENTS
from nexora.dashboard.api import DashboardAPIError

from .conftest import NAMESPACE, PROJECT


def agent_task(task_id: str, owner: str, status: str, updated_at: str) -> dict:
    return {
        "task_id": task_id,
        "owner_namespace": owner,
        "title": f"Agent task {task_id}",
        "status": status,
        "progress": 100 if status == "COMPLETED" else 40,
        "assigned_agent": "developer",
        "created_at": "2026-07-22T08:00:00+00:00",
        "updated_at": updated_at,
        "completed_at": updated_at if status == "COMPLETED" else None,
        "result_summary": "safe result",
        "error_code": None,
    }


def test_agent_control_center_safe_fields_owner_stats_and_status(dashboard_factory) -> None:
    app, _ = dashboard_factory()
    app.api.database.upsert_task(agent_task("NX-AGENT-001", NAMESPACE, "COMPLETED", "2026-07-22T08:10:00+00:00"))
    app.api.database.upsert_task(agent_task("NX-AGENT-002", NAMESPACE, "IN_PROGRESS", "2026-07-22T08:20:00+00:00"))
    app.api.database.upsert_task(agent_task("NX-AGENT-FOREIGN", "c" * 32, "COMPLETED", "2026-07-22T09:00:00+00:00"))
    app.api.database.set_agent_override("qa", False, "APR-READONLY01")

    items = app.api.list_agents()["items"]
    assert [item["id"] for item in items] == list(REQUIRED_AGENTS)
    required = {
        "id", "name", "description", "status", "role", "risk_level",
        "permissions", "allowed_tools", "restrictions", "completed_tasks", "last_activity",
    }
    assert all(required <= set(item) for item in items)
    developer = next(item for item in items if item["id"] == "developer")
    assert developer["status"] == "ACTIVE"
    assert developer["completed_tasks"] == 1
    assert developer["last_activity"] == "2026-07-22T08:20:00+00:00"
    assert next(item for item in items if item["id"] == "qa")["status"] == "DISABLED"
    forbidden_fields = {"source", "system_prompt", "workspace", "tools_denied", "token", "secret"}
    assert all(not forbidden_fields.intersection(item) for item in items)

    details = app.api.agent_details("developer")
    assert details["role"] and details["recent_tasks"][0]["id"] == "NX-AGENT-002"
    assert all(item["id"] != "NX-AGENT-FOREIGN" for item in details["recent_tasks"])
    with pytest.raises(DashboardAPIError) as missing:
        app.api.agent_details("unknown-agent")
    assert missing.value.status == 404 and missing.value.code == "AGENT_NOT_FOUND"


def test_agent_control_center_frontend_is_read_only() -> None:
    script = (PROJECT / "dashboard" / "frontend" / "app.js").read_text(encoding="utf-8")
    agent_page = script.split("async function agentPage", 1)[1].split("async function skillsPage", 1)[0]
    assert "Карточка агента" in agent_page
    assert "/actions" not in agent_page
    assert "Enable" not in agent_page
    assert "Disable" not in agent_page
    assert "Reload" not in agent_page
    assert "allowed_tools" in agent_page and "completed_tasks" in agent_page and "last_activity" in agent_page
