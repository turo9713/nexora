from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nexora.admin import AdminConsole
from nexora.agents.registry import AgentRegistry
from nexora.billing import BillingAccessDenied, BillingFoundation, BillingLimitReached
from nexora.cloud import CloudManager
from nexora.collaboration import TeamService
from nexora.database import SQLiteRepository
from nexora.integrations.telegram_runtime.services.audit_service import AuditService
from nexora.integrations.telegram_runtime.storage.audit_repository import AuditRepository
from nexora.security.policies import PolicyEngine
from nexora.subscriptions import SubscriptionError
from nexora.usage import UsageError


PROJECT = Path(__file__).resolve().parents[1]
ADMIN = "a" * 32
CUSTOMER = "b" * 32
OUTSIDER = "c" * 32


def platform(tmp_path: Path):
    database = SQLiteRepository(tmp_path / "state" / "nexora.sqlite3")
    database.migrate()
    agents = AgentRegistry(PROJECT / "agents").load()
    policy = PolicyEngine(agents, PROJECT, status_resolver=database.agent_enabled)
    audit_repository = AuditRepository(tmp_path / "audit")
    audit = AuditService(audit_repository, database=database)
    teams = TeamService(database, policy, audit)
    billing = BillingFoundation(database, audit)
    admin = AdminConsole(billing, ADMIN, policy)
    cloud = CloudManager(database, teams, billing, audit, ADMIN, policy)
    return database, teams, billing, admin, cloud, audit_repository


def approval(database: SQLiteRepository, owner: str, action_type: str, suffix: str) -> str:
    task_id = f"NX-BILLING-{suffix}"
    now = datetime.now(timezone.utc).isoformat()
    database.upsert_task({"task_id": task_id, "owner_namespace": owner, "title": "Billing approval", "status": "WAITING_APPROVAL", "progress": 50, "assigned_agent": "Orchestrator", "created_at": now, "updated_at": now, "completed_at": None, "result_summary": "", "error_code": None})
    approval_id = f"APR-{suffix:0<8}"[:12]
    database.upsert_approval({"approval_id": approval_id, "task_id": task_id, "owner_namespace": owner, "action_type": action_type, "status": "APPROVED", "expires_at": "2099-01-01T00:00:00+00:00", "used_at": now})
    return approval_id


def tenant(teams: TeamService, owner: str = CUSTOMER):
    organization = teams.create_organization(owner, "Customer Organization")
    workspace = teams.create_workspace(owner, organization["id"], "Primary Workspace")
    return organization, workspace


def test_seeded_plans_and_subscription_lifecycle(tmp_path: Path) -> None:
    database, teams, billing, _, _, _ = platform(tmp_path)
    organization, _ = tenant(teams)
    plans = billing.list_plans()
    assert [item["id"] for item in plans] == ["free", "starter", "pro", "team", "business", "enterprise"]
    assert plans[0]["limits"]["tasks_monthly"] == 100
    assert plans[2]["limits"]["agents_limit"] is None
    assert plans[3]["features"]["audit"] is True
    assert plans[5]["features"]["sso"] is True
    subscription = billing.subscription(CUSTOMER, organization["id"])
    assert subscription["plan_id"] == "free" and subscription["status"] == "ACTIVE"
    assert database.list_billing_events(organization["id"])[0]["event"] == "SUBSCRIPTION_CREATED"
    database.set_subscription(organization["id"], "free", "TRIAL", "2000-01-01T00:00:00+00:00")
    assert billing.subscription(CUSTOMER, organization["id"])["status"] == "EXPIRED"
    with pytest.raises(SubscriptionError):
        billing.limits_engine.check(organization["id"], "tasks_monthly")


def test_limits_allow_deny_and_monthly_reset(tmp_path: Path) -> None:
    database, teams, billing, _, _, _ = platform(tmp_path)
    organization, workspace = tenant(teams)
    with pytest.raises(BillingLimitReached, match="LIMIT_REACHED"):
        billing.check(CUSTOMER, organization["id"], "workspace_limit", 1)
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    for index in range(99):
        task_id = f"NX-QUOTA-{index:03d}"
        database.upsert_task({"task_id": task_id, "owner_namespace": CUSTOMER, "title": "Quota", "status": "COMPLETED", "progress": 100, "assigned_agent": "Developer", "created_at": f"{current_month}-01T00:00:00+00:00", "updated_at": f"{current_month}-01T00:01:00+00:00", "completed_at": f"{current_month}-01T00:01:00+00:00", "result_summary": "", "error_code": None})
        teams.link_task(CUSTOMER, workspace["id"], task_id)
    assert billing.check(CUSTOMER, organization["id"], "tasks_monthly", 1)["allowed"] is True
    task_id = "NX-QUOTA-100"
    database.upsert_task({"task_id": task_id, "owner_namespace": CUSTOMER, "title": "Quota", "status": "COMPLETED", "progress": 100, "assigned_agent": "Developer", "created_at": f"{current_month}-01T00:00:00+00:00", "updated_at": f"{current_month}-01T00:01:00+00:00", "completed_at": f"{current_month}-01T00:01:00+00:00", "result_summary": "", "error_code": None})
    teams.link_task(CUSTOMER, workspace["id"], task_id)
    with pytest.raises(BillingLimitReached):
        billing.check(CUSTOMER, organization["id"], "tasks_monthly", 1)
    with sqlite3.connect(database.path) as connection:
        connection.execute("UPDATE tasks SET created_at='2000-01-01T00:00:00+00:00' WHERE organization_id=?", (organization["id"],))
    assert billing.check(CUSTOMER, organization["id"], "tasks_monthly", 1)["current"] == 0


def test_usage_is_server_metered_immutable_and_tenant_isolated(tmp_path: Path) -> None:
    database, teams, billing, _, _, audit = platform(tmp_path)
    organization, workspace = tenant(teams)
    other, _ = tenant(teams, OUTSIDER)
    event = billing.record_runtime_usage(organization["id"], workspace["id"], "agent_runs", 1, source="workflow_runtime")
    assert billing.usage(CUSTOMER, organization["id"])["events"]["agent_runs"] == 1
    with pytest.raises(BillingAccessDenied):
        billing.usage(OUTSIDER, organization["id"])
    with pytest.raises(UsageError):
        billing.record_runtime_usage(organization["id"], workspace["id"], "agent_runs", 999, source="external_client")
    with sqlite3.connect(database.path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE usage_events SET value=999 WHERE id=?", (event["id"],))
    assert billing.usage(OUTSIDER, other["id"])["events"] == {}
    text = (audit.root / "events.jsonl").read_text(encoding="utf-8")
    assert "USAGE_RECORDED" in text and CUSTOMER not in text


def test_admin_plan_change_requires_exact_one_time_approval(tmp_path: Path) -> None:
    database, teams, billing, admin, _, _ = platform(tmp_path)
    organization, _ = tenant(teams)
    billing.subscription(CUSTOMER, organization["id"])
    action = f"billing:plan_change:{organization['id']}:pro"
    approved = approval(database, ADMIN, action, "PLAN0001")
    with pytest.raises(BillingAccessDenied):
        admin.change_plan(OUTSIDER, organization["id"], "pro", approved)
    changed = admin.change_plan(ADMIN, organization["id"], "pro", approved)
    assert changed["plan_id"] == "pro"
    with pytest.raises(BillingAccessDenied, match="approval unavailable"):
        admin.change_plan(ADMIN, organization["id"], "pro", approved)
    events = database.list_billing_events(organization["id"])
    assert events[0]["event"] == "PLAN_CHANGED"
    with sqlite3.connect(database.path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("DELETE FROM billing_events WHERE id=?", (events[0]["id"],))
    block = approval(database, ADMIN, f"billing:organization_block:{organization['id']}", "BLOCK001")
    admin.block(ADMIN, organization["id"], True, block)
    assert database.get_organization(organization["id"])["status"] == "SUSPENDED"
    with pytest.raises(BillingAccessDenied):
        billing.subscription(CUSTOMER, organization["id"])


def test_subscription_activation_cancellation_and_usage_metrics(tmp_path: Path) -> None:
    _, teams, billing, _, _, _ = platform(tmp_path)
    organization, workspace = tenant(teams)
    billing.subscriptions.change(organization["id"], "pro", status="TRIAL", expires_at="2099-01-01T00:00:00+00:00")
    assert billing.subscription(CUSTOMER, organization["id"])["status"] == "TRIAL"
    for metric, value, source in (("tasks_completed", 1, "task_runtime"), ("tasks_failed", 2, "task_runtime"), ("skill_runs", 3, "workflow_runtime"), ("workflow_duration_ms", 450, "workflow_runtime")):
        billing.record_runtime_usage(organization["id"], workspace["id"], metric, value, source=source)
    usage = billing.usage(CUSTOMER, organization["id"])["events"]
    assert usage == {"skill_runs": 3, "tasks_completed": 1, "tasks_failed": 2, "workflow_duration_ms": 450}
    billing.subscriptions.cancel(organization["id"])
    assert billing.subscription(CUSTOMER, organization["id"])["status"] == "CANCELLED"
    with pytest.raises(SubscriptionError):
        billing.limits_engine.check(organization["id"], "tasks_monthly")


def test_cloud_provisioning_is_metadata_only_and_approved(tmp_path: Path) -> None:
    database, _, billing, _, cloud, _ = platform(tmp_path)
    approved = approval(database, ADMIN, "cloud:tenant_provision", "CLOUD001")
    result = cloud.provision(ADMIN, CUSTOMER, "Cloud Customer", "Default", "team", approved)
    assert result["subscription"]["plan_id"] == "team"
    assert result["resource"] == {"id": result["resource"]["id"], "resource_type": "TENANT_METADATA", "status": "READY"}
    resources = database.list_cloud_resources(result["organization"]["id"])
    assert resources[0]["status"] == "READY"
    assert "provider" not in json.dumps(resources).casefold()
    with pytest.raises(BillingAccessDenied):
        cloud.provision(ADMIN, "d" * 32, "Replay", "Default", "free", approved)
    assert billing.subscription(CUSTOMER, result["organization"]["id"])["status"] == "ACTIVE"


def test_migration_007_backup_integrity_and_rollback(tmp_path: Path) -> None:
    database, teams, _, _, _, _ = platform(tmp_path)
    teams.create_organization(CUSTOMER, "Preserved Organization")
    backup = database.path.with_suffix(database.path.suffix + ".pre-v7.backup")
    assert backup.is_file()
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 6
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM organizations").fetchone()[0] == 0
    database.rollback(14)
    database.rollback(13)
    database.rollback(12)
    database.rollback(11)
    database.rollback(10)
    database.rollback(9)
    database.rollback(8)
    database.rollback(7)
    assert database.schema_version() == 6
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM organizations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='plans'").fetchone()[0] == 0
