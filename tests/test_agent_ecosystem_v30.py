from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from nexora.agents import AgentEcosystem
from nexora.agents.ecosystem_common import AgentEcosystemDenied, AgentEcosystemError
from nexora.agents.registry import AgentRegistry
from nexora.collaboration import TeamService
from nexora.database import SQLiteRepository
from nexora.integrations.telegram_runtime.services.audit_service import AuditService
from nexora.integrations.telegram_runtime.storage.audit_repository import AuditRepository
from nexora.marketplace.validation import PackageValidationError, PackageValidator
from nexora.security.policies import PolicyEngine
from nexora.sdk.python import NexoraSDK
from nexora.api.gateway.server import ROUTES
from nexora.api.auth import API_SCOPES
from nexora.dashboard.permissions import DashboardPermissions


PROJECT = Path(__file__).resolve().parents[1]
OWNER, OUTSIDER = "a" * 32, "b" * 32


def platform(tmp_path: Path):
    database = SQLiteRepository(tmp_path / "state" / "nexora.sqlite3")
    assert database.migrate() == 11
    registry = AgentRegistry(PROJECT / "agents").load()
    policy = PolicyEngine(registry, PROJECT, status_resolver=database.agent_enabled)
    audit_repository = AuditRepository(tmp_path / "audit")
    audit = AuditService(audit_repository, database=database)
    teams = TeamService(database, policy, audit)
    organization = teams.create_organization(OWNER, "Agent Lab")
    workspace = teams.create_workspace(OWNER, organization["id"], "Agent Workspace")
    ecosystem = AgentEcosystem(database, teams, policy, audit, memory_pepper=b"x" * 32)
    return database, teams, ecosystem, workspace, audit_repository


def approval(database: SQLiteRepository, action: str, suffix: str) -> str:
    task_id, approval_id = f"NX-V30-{suffix}", f"APR-{suffix:0<8}"[:12]
    database.upsert_task({"task_id": task_id, "owner_namespace": OWNER, "title": "Agent ecosystem approval", "status": "WAITING_APPROVAL", "progress": 50, "assigned_agent": "Orchestrator", "created_at": "2026-07-21T10:00:00+00:00", "updated_at": "2026-07-21T10:00:00+00:00", "completed_at": None, "result_summary": "", "error_code": None})
    database.upsert_approval({"approval_id": approval_id, "task_id": task_id, "owner_namespace": OWNER, "action_type": action, "status": "APPROVED", "expires_at": "2099-01-01T00:00:00+00:00", "used_at": "2026-07-21T10:01:00+00:00"})
    return approval_id


def manifest(agent_id: str) -> dict:
    return {"id": agent_id, "name": agent_id.replace("-", " ").title(), "version": "1.0.0", "description": "Safe custom agent", "goal": "Create reviewed workspace results", "role": "specialist", "skills": ["content-writer"], "knowledge": ["workspace-style"], "tools": ["text_generation", "workspace_read"], "permissions": ["workspace:read", "drafts:write"], "memory_scope": "AGENT", "approval_rules": ["publish", "deploy"]}


def create_agent(database, ecosystem, workspace, agent_id):
    action = f"agent_builder:create:{workspace['id']}:{agent_id}:1.0.0"
    return ecosystem.builder.create(OWNER, workspace["id"], manifest(agent_id), approval_id=approval(database, action, agent_id[-8:].upper()))


def test_builder_versioning_approval_and_forbidden_capabilities(tmp_path: Path) -> None:
    database, _, ecosystem, workspace, audit = platform(tmp_path)
    with pytest.raises(AgentEcosystemDenied):
        ecosystem.builder.create(OWNER, workspace["id"], manifest("safe-writer"), approval_id="")
    created = create_agent(database, ecosystem, workspace, "safe-writer")
    assert created["status"] == "ACTIVE" and created["security"]["shell"] is False
    assert ecosystem.builder.get(OWNER, workspace["id"], "safe-writer")["manifest"]["goal"] == created["goal"]
    unsafe = manifest("unsafe-agent"); unsafe["tools"] = ["shell"]
    with pytest.raises(AgentEcosystemError, match="AGENT_TOOL_DENIED"): ecosystem.builder.validate(unsafe)
    with sqlite3.connect(database.path) as connection:
        with pytest.raises(sqlite3.IntegrityError): connection.execute("UPDATE agent_versions SET checksum='tampered'")
    assert "approval_or_role_denied" in audit.path.read_text(encoding="utf-8")


def test_agent_teams_roles_workflow_and_cross_tenant_isolation(tmp_path: Path) -> None:
    database, teams, ecosystem, workspace, _ = platform(tmp_path)
    create_agent(database, ecosystem, workspace, "team-leader"); create_agent(database, ecosystem, workspace, "team-reviewer")
    action = f"agent_team:create:{workspace['id']}"
    team = ecosystem.teams.create(OWNER, workspace["id"], "Delivery Team", "team-leader", ["team-leader", "team-reviewer"], approval_id=approval(database, action, "TEAM0001"))
    assert team["members"][0]["role"] == "LEADER" and team["workflow"][-1] == "team-reviewer"
    org_b = teams.create_organization(OUTSIDER, "Other Org"); ws_b = teams.create_workspace(OUTSIDER, org_b["id"], "Other Workspace")
    with pytest.raises(AgentEcosystemDenied): ecosystem.teams.get(OUTSIDER, workspace["id"], team["id"])
    assert ecosystem.teams.list(OUTSIDER, ws_b["id"]) == []


def test_planning_is_policy_checked_and_never_executes(tmp_path: Path) -> None:
    _, _, ecosystem, workspace, _ = platform(tmp_path)
    plan = ecosystem.planning.create(OWNER, workspace["id"], "Подготовить безопасный план статьи")
    assert plan["status"] == "READY" and len(plan["steps"]) == 4
    assert all(step["risk"] == "LOW" for step in plan["steps"])
    with pytest.raises(AgentEcosystemError, match="AGENT_PLAN_FORBIDDEN"): ecosystem.planning.create(OWNER, workspace["id"], "read secret token")


def test_memory_scopes_are_isolated_and_audited(tmp_path: Path) -> None:
    database, _, ecosystem, workspace, audit = platform(tmp_path)
    personal = ecosystem.memory.put(OWNER, workspace["id"], "tone", "formal and concise", scope="PERSONAL")
    agent = ecosystem.memory.put(OWNER, workspace["id"], "style", "short drafts", scope="AGENT", agent_id="content")
    assert ecosystem.memory.list(OWNER, workspace["id"], scope="PERSONAL") == [personal]
    assert ecosystem.memory.list(OWNER, workspace["id"], scope="AGENT", agent_id="content") == [agent]
    with pytest.raises(AgentEcosystemDenied): ecosystem.memory.list(OUTSIDER, workspace["id"], scope="PERSONAL")
    text = audit.path.read_text(encoding="utf-8")
    assert "formal and concise" not in text and OWNER not in text
    with database._connect() as connection:
        stored = connection.execute("SELECT value FROM agent_memory WHERE id=?", (personal["id"],)).fetchone()[0]
    assert "formal and concise" not in stored


def test_evaluation_is_server_only_immutable_and_tenant_scoped(tmp_path: Path) -> None:
    database, _, ecosystem, workspace, _ = platform(tmp_path)
    result = ecosystem.evaluation.record(OWNER, workspace["id"], "developer", {"accuracy": 95, "reliability": 90, "safety": 100, "speed": 80, "cost": 75})
    assert result["grade"] in {"A+", "A"} and ecosystem.evaluation.list(OWNER, workspace["id"])[0]["id"] == result["id"]
    with pytest.raises(AgentEcosystemError): ecosystem.evaluation.record(OWNER, workspace["id"], "developer", {"accuracy": 100}, source="client")
    with sqlite3.connect(database.path) as connection:
        with pytest.raises(sqlite3.IntegrityError): connection.execute("UPDATE agent_evaluations SET safety=0")


def test_marketplace_agent_packages_support_teams_and_departments() -> None:
    base = {"id":"safe-team", "name":"Safe Team", "type":"AGENT", "version":"1.0.0", "author":"Nexora", "description":"Declarative agent team", "category":"agents", "permissions":{"filesystem":{"scope":"workspace"},"network":{"mode":"none"},"shell":False}, "risk_level":"LOW", "requirements":[], "compatibility":{"minimum_nexora":"3.0.0"}, "security":{"sandbox":True,"secret_access":False,"docker_access":False}}
    for kind in ("SINGLE_AGENT", "AGENT_TEAM", "AI_DEPARTMENT"):
        assert PackageValidator().validate({**base, "package_kind":kind}).manifest["package_kind"] == kind
    with pytest.raises(PackageValidationError): PackageValidator().validate({**base, "package_kind":"EXECUTABLE"})


def test_migration_010_backup_integrity_and_rollback(tmp_path: Path) -> None:
    database = SQLiteRepository(tmp_path / "state" / "nexora.sqlite3")
    assert database.migrate() == 11 and database.check()
    assert database.path.with_suffix(database.path.suffix + ".pre-v10.backup").is_file()
    database.rollback(11)
    database.rollback(10)
    assert database.schema_version() == 9
    with database._connect() as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='agent_teams'").fetchone()[0] == 0


def test_sdk_and_api_dashboard_surfaces_remain_policy_checked(tmp_path: Path) -> None:
    database, _, ecosystem, workspace, _ = platform(tmp_path)
    sdk = NexoraSDK(ecosystem, OWNER, workspace["id"])
    action = f"agent_builder:create:{workspace['id']}:sdk-writer:1.0.0"
    created = sdk.create_agent(manifest("sdk-writer"), approval(database, action, "SDK00001"))
    assert created["id"] == "sdk-writer"
    assert sdk.connect_skill("sdk-writer", "content-writer")["status"] == "DECLARED"
    plan = sdk.create_plan("Сформировать безопасный отчёт")
    assert sdk.result(plan["id"]) == {"plan_id": plan["id"], "status": "READY", "execution": "not_started"}
    assert sdk.start_workflow("Проверить документ")["execution"] == "not_started"
    assert ROUTES[("GET", "/api/v1/agent-definitions")][0] == "agent_ecosystem:read"
    assert ROUTES[("POST", "/api/v1/agent-definitions")][0] == "agent_ecosystem:manage"
    assert {"agent_ecosystem:read", "agent_ecosystem:manage"}.issubset(API_SCOPES)
    assert "agent_ecosystem:manage" in DashboardPermissions.ALLOWED
