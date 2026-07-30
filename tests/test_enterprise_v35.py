from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nexora.agents.registry import AgentRegistry
from nexora.api.auth import APIKeyPrincipal
from nexora.api.auth.api_keys import API_SCOPES
from nexora.api.gateway.server import ROUTES
from nexora.api.gateway.service import APIGateway, APIGatewayError
from nexora.collaboration import TeamService
from nexora.database import SQLiteRepository
from nexora.enterprise import EnterpriseAccessDenied, EnterpriseService, EnterpriseValidationError
from nexora.dashboard.permissions import DashboardPermissions
from nexora.integrations.telegram_runtime.services.audit_service import AuditService
from nexora.integrations.telegram_runtime.storage.audit_repository import AuditRepository
from nexora.security.policies import PolicyEngine


PROJECT = Path(__file__).resolve().parents[1]
OWNER = "a" * 32
FOREIGN = "f" * 32


def platform(tmp_path: Path):
    database = SQLiteRepository(tmp_path / "database" / "nexora.sqlite3")
    assert database.migrate() == 14
    registry = AgentRegistry(PROJECT / "agents").load()
    audit = AuditService(AuditRepository(tmp_path / "audit"), database=database)
    policy = PolicyEngine(registry, PROJECT, status_resolver=database.agent_enabled)
    teams = TeamService(database, policy, audit)
    service = EnterpriseService(database, teams, policy, audit, registry, tmp_path / "state", tmp_path / "backups")
    return database, teams, service


def approval(database: SQLiteRepository, owner: str, action_type: str, suffix: str) -> str:
    approval_id = f"APR-{suffix:0<8}"[:12]
    now = datetime.now(timezone.utc).isoformat()
    database.upsert_task({
        "task_id": f"NX-{suffix}", "owner_namespace": owner, "title": "Approved enterprise change",
        "status": "WAITING_APPROVAL", "progress": 50, "created_at": now, "updated_at": now,
    })
    database.upsert_approval({
        "approval_id": approval_id,
        "task_id": f"NX-{suffix}",
        "owner_namespace": owner,
        "action_type": action_type,
        "status": "APPROVED",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        "used_at": None,
    })
    return approval_id


def test_migration_012_backup_integrity_and_rollback(tmp_path: Path) -> None:
    database, _, _ = platform(tmp_path)
    backup = database.path.with_suffix(database.path.suffix + ".pre-v12.backup")
    assert backup.is_file()
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    database.rollback(14)
    database.rollback(13)
    database.rollback(12)
    assert database.schema_version() == 11
    with sqlite3.connect(database.path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "enterprise_policies" not in tables
    assert "notifications" in tables


def test_policy_create_version_rollback_requires_approval_and_is_tenant_scoped(tmp_path: Path) -> None:
    database, teams, service = platform(tmp_path)
    organization = teams.create_organization(OWNER, "Owner Enterprise")
    workspace = teams.create_workspace(OWNER, organization["id"], "Security")
    foreign_org = teams.create_organization(FOREIGN, "Foreign Enterprise")
    foreign_workspace = teams.create_workspace(FOREIGN, foreign_org["id"], "Foreign")

    with pytest.raises(EnterpriseAccessDenied):
        service.create_policy(OWNER, workspace["id"], "Production Safety", "SECURITY_POLICY", {"allow_shell": False}, approval_id="")
    with pytest.raises(EnterpriseValidationError):
        service.create_policy(OWNER, workspace["id"], "Unsafe", "SECURITY_POLICY", {"allow_shell": True}, approval_id="APR-INVALID0")

    create_action = f"enterprise:policy_create:{organization['id']}"
    policy = service.create_policy(OWNER, workspace["id"], "Production Safety", "SECURITY_POLICY", {"require_approval": True, "allow_shell": False}, approval_id=approval(database, OWNER, create_action, "CREATE01"))
    assert policy["current_version"] == 1
    update_action = f"enterprise:policy_update:{policy['id']}"
    updated = service.update_policy(OWNER, workspace["id"], policy["id"], {"require_approval": True, "external_write": False}, "Tighten writes", approval_id=approval(database, OWNER, update_action, "UPDATE01"))
    assert updated["current_version"] == 2
    rollback_action = f"enterprise:policy_rollback:{policy['id']}"
    rolled = service.rollback_policy(OWNER, workspace["id"], policy["id"], 1, approval_id=approval(database, OWNER, rollback_action, "ROLLBACK"))
    assert rolled["current_version"] == 3 and rolled["rules"]["allow_shell"] is False
    with pytest.raises(EnterpriseAccessDenied):
        service.list_policies(OWNER, foreign_workspace["id"])
    assert service.list_policies(FOREIGN, foreign_workspace["id"])["items"] == []


def test_advanced_audit_is_immutable_hashed_and_redacted(tmp_path: Path) -> None:
    database, teams, service = platform(tmp_path)
    organization = teams.create_organization(OWNER, "Audit Organization")
    workspace = teams.create_workspace(OWNER, organization["id"], "Audit Workspace")
    action = f"enterprise:policy_create:{organization['id']}"
    service.create_policy(OWNER, workspace["id"], "Data Safety", "DATA_POLICY", {"external_write": False}, approval_id=approval(database, OWNER, action, "AUDIT001"))
    events = service.security_events(OWNER, workspace["id"])
    assert events["chain_valid"] is True and events["items"]
    encoded = json.dumps(events)
    assert OWNER not in encoded and "actor_hash" not in encoded and "approval" not in encoded.lower()
    with pytest.raises(sqlite3.IntegrityError):
        with database._connect() as connection:
            connection.execute("UPDATE security_events SET result='TAMPERED'")


def test_sla_storage_profiles_sso_and_compliance_are_safe(tmp_path: Path) -> None:
    database, teams, service = platform(tmp_path)
    organization = teams.create_organization(OWNER, "Operations Organization")
    workspace = teams.create_workspace(OWNER, organization["id"], "Operations")
    (tmp_path / "state").mkdir(mode=0o700)
    if os.name == "posix":
        os.chmod(tmp_path / "state", 0o700)
    assert service.sla(OWNER, workspace["id"])["task_success_rate"] == 100.0
    storage = service.storage_health(OWNER, workspace["id"])
    assert storage["database"] == "OK" and storage["backup"] == "UNKNOWN" and storage["status"] == "DEGRADED"
    profiles = service.deployment_profiles(OWNER, workspace["id"])["items"]
    assert {item["name"] for item in profiles} == {"Development", "Staging", "Production", "Enterprise"}
    assert all(item["security_settings"]["deny_by_default"] for item in profiles)
    sso = service.sso_foundation(OWNER, workspace["id"])
    assert sso["configured"] is False and all(item["enabled"] is False for item in sso["providers"])
    compliance = service.compliance(OWNER, workspace["id"])
    assert compliance["certified"] is False and compliance["controls"]["tenant_isolation"] is True


def test_public_gateway_enterprise_scope_is_fail_closed(tmp_path: Path) -> None:
    database, teams, enterprise = platform(tmp_path)
    organization = teams.create_organization(OWNER, "API Organization")
    workspace = teams.create_workspace(OWNER, organization["id"], "API Workspace")
    principal = APIKeyPrincipal("KEY-000000000001", OWNER, "enterprise", frozenset({"enterprise:read"}))
    gateway = object.__new__(APIGateway)
    gateway.enterprise = enterprise
    assert gateway.enterprise_read(principal, "policies", {"workspace_id": workspace["id"]})["items"] == []
    with pytest.raises(APIGatewayError) as error:
        gateway.enterprise_read(principal, "policies", {"workspace_id": "WS-UNKNOWN"})
    assert error.value.status == 404


def test_dashboard_assets_expose_read_only_enterprise_center() -> None:
    html = (PROJECT / "dashboard" / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (PROJECT / "dashboard" / "frontend" / "app.js").read_text(encoding="utf-8")
    assert all(route in html for route in ("/security-center", "/policies", "/sla", "/storage-health", "/enterprise"))
    assert "/api/enterprise/security-center" in js and "/api/enterprise/storage-health" in js
    assert "Policy changes are versioned and cannot be applied from this read-only view." in js
    server = (PROJECT / "dashboard" / "backend" / "server.py").read_text(encoding="utf-8")
    assert all(route in server for route in ("/security-center", "/policies", "/sla", "/storage-health", "/enterprise"))


def test_enterprise_http_boundaries_require_explicit_read_scope() -> None:
    expected = {
        ("GET", "/api/v1/policies"),
        ("GET", "/api/v1/security/events"),
        ("GET", "/api/v1/sla"),
        ("GET", "/api/v1/storage/health"),
    }
    assert all(ROUTES[route][0] == "enterprise:read" for route in expected)
    assert "enterprise:read" in API_SCOPES
    assert "enterprise:read" in DashboardPermissions.ALLOWED
    assert not any(method != "GET" and path in {item[1] for item in expected} for method, path in ROUTES)


def test_storage_corruption_is_detected_without_mutation(tmp_path: Path) -> None:
    database, teams, service = platform(tmp_path)
    organization = teams.create_organization(OWNER, "Storage Organization")
    workspace = teams.create_workspace(OWNER, organization["id"], "Storage")
    database.path.write_bytes(b"not-a-sqlite-database")
    assert service._database_integrity() == "ERROR"
