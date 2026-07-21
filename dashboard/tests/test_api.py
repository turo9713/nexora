from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexora.dashboard.api import DashboardAPIError

from .conftest import NAMESPACE


def task(task_id: str, owner: str, title: str = "Dashboard task") -> dict:
    return {
        "task_id": task_id,
        "owner_namespace": owner,
        "title": title,
        "status": "COMPLETED",
        "progress": 100,
        "assigned_agent": "developer",
        "created_at": "2026-07-21T08:00:00+00:00",
        "updated_at": "2026-07-21T08:01:00+00:00",
        "completed_at": "2026-07-21T08:01:00+00:00",
        "result_summary": "Authorization: Bearer fixture-dashboard-secret",
        "error_code": None,
    }


def test_health_tasks_idor_and_redaction(dashboard_factory) -> None:
    app, _ = dashboard_factory()
    database = app.api.database
    database.upsert_task(task("NX-OWNER-001", NAMESPACE))
    database.upsert_task(task("NX-FOREIGN-001", "c" * 32, "Foreign task"))
    health = app.api.health()
    assert health["runtime"] == "OK"
    assert health["gateway"] == "OK" and health["telegram"] == "OK"
    assert health["templates"]["ok"] is True
    listed = app.api.list_tasks({})["items"]
    assert [item["id"] for item in listed] == ["NX-OWNER-001"]
    details = app.api.task_details("NX-OWNER-001")
    assert "fixture-dashboard-secret" not in json.dumps(details)
    with pytest.raises(DashboardAPIError) as denied:
        app.api.task_details("NX-FOREIGN-001")
    assert denied.value.status == 404


def test_templates_playground_and_approval_reuse_existing_engine(dashboard_factory) -> None:
    app, _ = dashboard_factory()
    items = app.api.list_templates()["items"]
    assert any(item["id"] == "content-factory" for item in items)
    direct = app.api.request_template_install("code-review", "template-session-direct")
    assert direct["status"] == "ACTIVE"
    pending = app.api.request_template_install("content-factory", "template-session-approval")
    assert pending["status"] == "WAITING_APPROVAL"
    approved = app.api.decide_approval(pending["approval_id"], "approve")
    assert approved["execution"] == "COMPLETED"
    assert any(item["template_id"] == "content-factory" for item in app.api.database.list_template_installations(NAMESPACE))
    playground = app.api.playground_examples()
    assert playground["mode"] == "SANDBOX_ONLY" and playground["production_tools"] is False


def test_team_dashboard_is_owner_scoped(dashboard_factory) -> None:
    app, _ = dashboard_factory()
    organizations = app.api.list_organizations()["items"]
    workspaces = app.api.list_workspaces({})["items"]
    assert len(organizations) == 1 and organizations[0]["name"] == "Personal Organization"
    assert len(workspaces) == 1 and workspaces[0]["role"] == "OWNER"
    members = app.api.list_members({"workspace_id": workspaces[0]["id"]})["items"]
    assert len(members) == 1 and members[0]["role"] == "OWNER"
    assert app.api.list_knowledge({"workspace_id": workspaces[0]["id"]})["items"] == []
    health = app.api.health()
    assert health["tenancy"] == {"organizations": 1, "workspaces": 1}


def test_agent_change_requires_existing_approval_engine(dashboard_factory) -> None:
    app, _ = dashboard_factory()
    request = app.api.request_agent_action("developer", "disable", "session-a")
    assert request["status"] == "WAITING_APPROVAL"
    before = app.api.agent_details("developer")
    assert before["enabled"] is True
    approved = app.api.decide_approval(request["approval_id"], "approve")
    assert approved["status"] == "APPROVED" and approved["execution"] == "COMPLETED"
    assert app.api.agent_details("developer")["enabled"] is False
    with pytest.raises(DashboardAPIError) as replay:
        app.api.decide_approval(request["approval_id"], "approve")
    assert replay.value.code == "APPROVAL_UNAVAILABLE"

    rejected_request = app.api.request_agent_action("developer", "enable", "session-b")
    rejected = app.api.decide_approval(rejected_request["approval_id"], "reject")
    assert rejected["status"] == "REJECTED"
    assert app.api.agent_details("developer")["enabled"] is False


def test_expired_approval_does_not_execute(dashboard_factory) -> None:
    app, _ = dashboard_factory()
    request = app.api.request_agent_action("content", "disable", "session-expired")
    approval = app.api.approvals.repository.get(NAMESPACE, request["approval_id"])
    assert approval is not None
    approval["expires_at"] = "2000-01-01T00:00:00+00:00"
    app.api.approvals.repository.save(NAMESPACE, approval)
    with pytest.raises(DashboardAPIError) as expired:
        app.api.decide_approval(request["approval_id"], "approve")
    assert expired.value.code == "APPROVAL_EXPIRED"
    assert app.api.agent_details("content")["enabled"] is True


def test_audit_is_sanitized_and_created(dashboard_factory) -> None:
    app, _ = dashboard_factory()
    app.api.audit.record(
        "LOGIN_FAILED",
        severity="SECURITY",
        source="dashboard_auth",
        action_result="DENIED",
        token="fixture-token-value",
        reason="invalid_credentials",
    )
    response = app.api.audit_events({"severity": "SECURITY"})
    serialized = json.dumps(response)
    assert "fixture-token-value" not in serialized
    assert response["items"][0]["event"] == "LOGIN_FAILED"


def test_skill_listing_and_changes_use_existing_approval(dashboard_factory) -> None:
    app, _ = dashboard_factory()
    listed = app.api.list_skills()["items"]
    assert {item["id"] for item in listed} == {"content-writer", "research", "github-assistant", "github-agent", "analytics"}
    assert next(item for item in listed if item["id"] == "content-writer")["status"] == "ACTIVE"

    request = app.api.request_skill_action("content-writer", "disable", "skill-session")
    assert request["status"] == "WAITING_APPROVAL"
    approved = app.api.decide_approval(request["approval_id"], "approve")
    assert approved["execution"] == "COMPLETED"
    assert app.api.skill_details("content-writer")["status"] == "DISABLED"
    with pytest.raises(DashboardAPIError) as replay:
        app.api.decide_approval(request["approval_id"], "approve")
    assert replay.value.code == "APPROVAL_UNAVAILABLE"

    reload_request = app.api.request_skill_action("research", "reload", "skill-session")
    rejected = app.api.decide_approval(reload_request["approval_id"], "reject")
    assert rejected["status"] == "REJECTED"
    assert app.api.skill_details("research")["status"] == "ACTIVE"


def test_api_key_and_webhook_lifecycle_require_approval(dashboard_factory) -> None:
    app, _ = dashboard_factory()
    key_request = app.api.request_api_key_create(
        {"name": "Integration test", "scopes": ["tasks:create", "tasks:read"]},
        "dashboard-session",
    )
    record = app.api.database.get_api_key_record(key_request["key_id"])
    assert record is not None and record["status"] == "PENDING" and record["key_hash"] == ""
    approved = app.api.decide_approval(key_request["approval_id"], "approve")
    plaintext = approved.pop("one_time_secret")
    assert plaintext.startswith("nx_live_")
    assert plaintext not in json.dumps(app.api.list_api_keys())
    assert plaintext not in app.api.database.path.read_bytes().decode("latin1")
    principal = app.api.api_keys.authenticate(plaintext, "tasks:read")
    assert principal is not None
    assert app.api.api_keys.authenticate(plaintext, "agents:read") is None

    disable = app.api.request_api_key_action(key_request["key_id"], "disable", "dashboard-session")
    app.api.decide_approval(disable["approval_id"], "approve")
    assert app.api.api_keys.authenticate(plaintext, "tasks:read") is None

    hook_request = app.api.request_webhook_create(
        {"url": "https://example.com/nexora", "events": ["TASK_COMPLETED"]},
        "dashboard-session",
    )
    hook_approved = app.api.decide_approval(hook_request["approval_id"], "approve")
    assert hook_approved["one_time_secret"]
    assert app.api.list_webhooks()["items"][0]["status"] == "ACTIVE"
    assert "secret" not in json.dumps(app.api.list_webhooks()).casefold()
