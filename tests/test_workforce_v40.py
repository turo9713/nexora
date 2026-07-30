from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nexora.agents.registry import AgentRegistry
from nexora.collaboration import TeamService
from nexora.database import SQLiteRepository
from nexora.integrations.telegram_runtime.services.audit_service import AuditService
from nexora.integrations.telegram_runtime.storage.audit_repository import AuditRepository
from nexora.marketplace import MarketplaceService
from nexora.security.policies import PolicyEngine
from nexora.workforce import AIWorkforceError, AIWorkforceService
from nexora.workforce.catalog import CATEGORIES, OFFICIAL_EMPLOYEES, OFFICIAL_SKILLS, OFFICIAL_WORKFLOWS


PROJECT = Path(__file__).resolve().parents[1]
OWNER = "a" * 32
OUTSIDER = "b" * 32


def platform(tmp_path: Path):
    database = SQLiteRepository(tmp_path / "state" / "nexora.sqlite3")
    assert database.migrate() == 14
    registry = AgentRegistry(PROJECT / "agents").load()
    policy = PolicyEngine(registry, PROJECT, status_resolver=database.agent_enabled)
    audit = AuditService(AuditRepository(tmp_path / "audit"), database=database)
    teams = TeamService(database, policy, audit)
    organization = teams.create_organization(OWNER, "Workforce Organization")
    workspace = teams.create_workspace(OWNER, organization["id"], "Workforce Workspace")
    service = AIWorkforceService(MarketplaceService(database, teams, policy, audit))
    assert service.bootstrap_official(OWNER) == {"created": 24, "indexed": 24}
    return database, teams, service, workspace


def approval(database: SQLiteRepository, action_type: str, suffix: str) -> str:
    now = datetime.now(timezone.utc).isoformat()
    task_id = f"NX-WORKFORCE-{suffix}"
    approval_id = f"APR-{suffix:0<8}"[:12]
    database.upsert_task({"task_id": task_id, "owner_namespace": OWNER, "title": "Workforce approval", "status": "WAITING_APPROVAL", "progress": 50, "assigned_agent": "Orchestrator", "created_at": now, "updated_at": now, "completed_at": None, "result_summary": "", "error_code": None})
    database.upsert_approval({"approval_id": approval_id, "task_id": task_id, "owner_namespace": OWNER, "action_type": action_type, "status": "APPROVED", "expires_at": "2099-01-01T00:00:00+00:00", "used_at": now})
    return approval_id


def test_official_catalog_categories_and_complete_employee_profiles(tmp_path: Path) -> None:
    _, _, service, workspace = platform(tmp_path)
    values = service.catalog(OWNER, workspace_id=workspace["id"])
    assert len(values) == len(OFFICIAL_EMPLOYEES) + len(OFFICIAL_WORKFLOWS) + len(OFFICIAL_SKILLS) == 24
    assert set(CATEGORIES) >= {value["category"] for value in values}
    assert len(service.catalog(OWNER, kind="EMPLOYEE")) == 14
    assert len(service.catalog(OWNER, kind="WORKFLOW")) == 6
    assert len(service.catalog(OWNER, kind="SKILL")) == 4
    detail = service.item(OWNER, "developer", workspace_id=workspace["id"])
    assert detail["listing_kind"] == "EMPLOYEE"
    assert detail["manifest"]["permissions"]["shell"] is False
    assert detail["compatibility"]["minimum_nexora"] == "4.0.0"
    assert {"changelog", "screenshots", "documentation", "tags", "price_cents"} <= set(detail)


def test_one_click_install_builds_real_workspace_resources_and_team_projection(tmp_path: Path) -> None:
    database, _, service, workspace = platform(tmp_path)
    result = service.install(OWNER, workspace["id"], "developer")
    assert result["status"] == "ACTIVE"
    resources = database.list_workforce_resources(result["id"])
    assert {value["resource_type"] for value in resources} == {
        "WORKSPACE_BINDING", "MEMORY_PROFILE", "PERMISSIONS", "WORKFLOW", "PROMPT", "SETTINGS",
    }
    assert next(value for value in resources if value["resource_type"] == "WORKSPACE_BINDING")["configuration"]["workspace_id"] == workspace["id"]
    assert next(value for value in resources if value["resource_type"] == "PERMISSIONS")["configuration"]["shell"] is False
    team = service.team(OWNER, workspace["id"])
    assert team[0]["id"] == "developer" and team[0]["memory"] == "WORKSPACE_BOUND"
    assert service.install(OWNER, workspace["id"], "developer")["id"] == result["id"]


def test_integration_wizard_rejects_inline_secrets_and_requires_one_time_approval(tmp_path: Path) -> None:
    database, _, service, workspace = platform(tmp_path)
    service.install(OWNER, workspace["id"], "telegram-manager")
    with pytest.raises(AIWorkforceError, match="INLINE_SECRET_FORBIDDEN"):
        service.request_integration(OWNER, workspace["id"], "telegram-manager", "TELEGRAM", secret_reference=None, configuration={"token": "secret"})
    pending = service.request_integration(OWNER, workspace["id"], "telegram-manager", "TELEGRAM", secret_reference="TELEGRAM_BOT_TOKEN", configuration={"mode": "polling"})
    assert pending["status"] == "PENDING"
    action = f"workforce:integration:{workspace['id']}:telegram-manager:TELEGRAM"
    approved = approval(database, action, "INTG0001")
    assert service.activate_integration(OWNER, workspace["id"], "telegram-manager", "TELEGRAM", approval_id=approved)["status"] == "ACTIVE"
    with pytest.raises(Exception):
        service.activate_integration(OWNER, workspace["id"], "telegram-manager", "TELEGRAM", approval_id=approved)
    raw = json.dumps(database.get_integration_wizard(service.database.get_workforce_installation(workspace["id"], "telegram-manager")["id"], "TELEGRAM"))
    assert "secret\"" not in raw.casefold() and "authorization" not in raw.casefold()


def test_uninstall_is_approval_gated_and_tenant_isolated(tmp_path: Path) -> None:
    database, teams, service, workspace = platform(tmp_path)
    service.install(OWNER, workspace["id"], "qa-engineer")
    with pytest.raises(Exception):
        service.uninstall(OWNER, workspace["id"], "qa-engineer", approval_id="")
    approved = approval(database, f"workforce:uninstall:{workspace['id']}:qa-engineer", "UNIN0001")
    assert service.uninstall(OWNER, workspace["id"], "qa-engineer", approval_id=approved)["status"] == "UNINSTALLED"
    outsider_org = teams.create_organization(OUTSIDER, "Outsider")
    outsider_workspace = teams.create_workspace(OUTSIDER, outsider_org["id"], "Outsider Workspace")
    assert service.team(OUTSIDER, outsider_workspace["id"]) == []
    with pytest.raises(AIWorkforceError, match="WORKFORCE_RESOURCE_NOT_FOUND"):
        service.team(OUTSIDER, workspace["id"])


def test_migration_013_backup_integrity_rollback_and_immutable_earnings(tmp_path: Path) -> None:
    database, _, service, _ = platform(tmp_path)
    backup = database.path.with_suffix(database.path.suffix + ".pre-v13.backup")
    assert backup.is_file()
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 12
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    publisher = database.list_publishers(OWNER)[0]
    with sqlite3.connect(database.path) as connection:
        connection.execute("INSERT INTO marketplace_earnings(id,publisher_id,item_id,gross_cents,commission_cents,creator_cents,status,created_at) VALUES('EARN-1',?,'developer',1000,150,850,'ESTIMATED',datetime('now'))", (publisher["id"],))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE marketplace_earnings SET creator_cents=900 WHERE id='EARN-1'")
    assert service.developer_portal(OWNER)["payments_enabled"] is False
    database.rollback(14)
    database.rollback(13)
    assert database.schema_version() == 12
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='workforce_installations'").fetchone()[0] == 0


def test_dashboard_and_public_api_surfaces_are_authenticated_and_no_gateway_access() -> None:
    dashboard_server = (PROJECT / "dashboard" / "backend" / "server.py").read_text(encoding="utf-8")
    api_server = (PROJECT / "api" / "gateway" / "server.py").read_text(encoding="utf-8")
    frontend = (PROJECT / "dashboard" / "frontend" / "app.js").read_text(encoding="utf-8")
    permissions = (PROJECT / "dashboard" / "permissions" / "service.py").read_text(encoding="utf-8")
    assert "/api/workforce/catalog" in dashboard_server
    assert "/api/v1/workforce" in api_server
    assert '"workforce:read"' in permissions and '"workforce:manage"' in permissions
    assert "/marketplace/workflows" in frontend and "/ai-team" in frontend and "/developer" in frontend
    assert "127.0.0.1:18789" not in frontend and "/v1/responses" not in frontend
