from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from nexora.agents.registry import AgentRegistry
from nexora.collaboration import TeamAccessDenied, TeamService, TeamValidationError
from nexora.database import SQLiteRepository
from nexora.integrations.telegram_runtime.services.audit_service import AuditService
from nexora.integrations.telegram_runtime.storage.audit_repository import AuditRepository
from nexora.permissions import RBAC
from nexora.security.policies import PolicyEngine


PROJECT = Path(__file__).resolve().parents[1]
OWNER_A = "a" * 32
OWNER_B = "b" * 32


def platform(tmp_path: Path):
    database = SQLiteRepository(tmp_path / "state" / "nexora.sqlite3")
    database.migrate()
    agents = AgentRegistry(PROJECT / "agents").load()
    policy = PolicyEngine(agents, PROJECT, status_resolver=database.agent_enabled)
    audit_repository = AuditRepository(tmp_path / "audit")
    audit = AuditService(audit_repository, database=database)
    return database, TeamService(database, policy, audit), audit_repository


def approval(database: SQLiteRepository, owner: str, action_type: str, suffix: str) -> str:
    task_id = f"NX-TEAM-{suffix}"
    database.upsert_task({
        "task_id": task_id, "owner_namespace": owner, "title": "Approved team action",
        "status": "WAITING_APPROVAL", "progress": 50, "assigned_agent": "Orchestrator",
        "created_at": "2026-07-21T10:00:00+00:00", "updated_at": "2026-07-21T10:00:00+00:00",
        "completed_at": None, "result_summary": "", "error_code": None,
    })
    approval_id = f"APR-{suffix:0<8}"[:12]
    database.upsert_approval({
        "approval_id": approval_id, "task_id": task_id, "owner_namespace": owner,
        "action_type": action_type, "status": "APPROVED", "expires_at": "2099-01-01T00:00:00+00:00",
        "used_at": "2026-07-21T10:01:00+00:00",
    })
    return approval_id


def test_organizations_workspaces_and_rbac_are_fail_closed(tmp_path: Path) -> None:
    database, teams, _ = platform(tmp_path)
    organization = teams.create_organization(OWNER_A, "Acme")
    workspace = teams.create_workspace(OWNER_A, organization["id"], "Marketing", "Content team")
    assert teams.list_organizations(OWNER_A)[0]["id"] == organization["id"]
    assert teams.list_workspaces(OWNER_A)[0]["role"] == "OWNER"
    assert RBAC().evaluate("VIEWER", "tasks:read").allowed
    assert not RBAC().evaluate("VIEWER", "tasks:create").allowed
    assert not RBAC().evaluate("UNKNOWN", "tasks:read").allowed
    assert database.membership(OWNER_A, workspace["id"])["organization_id"] == organization["id"]


def test_invite_is_approved_one_time_and_role_escalation_is_denied(tmp_path: Path) -> None:
    database, teams, _ = platform(tmp_path)
    organization = teams.create_organization(OWNER_A, "Acme")
    workspace = teams.create_workspace(OWNER_A, organization["id"], "Engineering")
    action = f"team:workspace_invite:{workspace['id']}"
    first = approval(database, OWNER_A, action, "INVITE01")
    admin = teams.invite(OWNER_A, workspace["id"], "c" * 64, "Admin User", "ADMIN", approval_id=first)
    assert admin["role"] == "ADMIN"
    with pytest.raises(TeamAccessDenied, match="approval unavailable"):
        teams.invite(OWNER_A, workspace["id"], "d" * 64, "Replay", "VIEWER", approval_id=first)
    admin_actor = "usr-" + "c" * 64
    admin_workspace = teams.create_workspace(admin_actor, organization["id"], "Admin Workspace")
    assert database.membership(admin_actor, admin_workspace["id"])["role"] == "ADMIN"
    elevated = approval(database, admin_actor, action, "INVITE02")
    with pytest.raises(TeamAccessDenied, match="role escalation"):
        teams.invite(admin_actor, workspace["id"], "e" * 64, "Other Admin", "ADMIN", approval_id=elevated)


def test_organization_archive_and_workspace_components_require_exact_approval(tmp_path: Path) -> None:
    database, teams, _ = platform(tmp_path)
    organization = teams.create_organization(OWNER_A, "Controlled Org")
    workspace = teams.create_workspace(OWNER_A, organization["id"], "Controlled Workspace")
    wrong = approval(database, OWNER_A, "team:workspace_invite:WS-WRONG000000", "WRONG001")
    with pytest.raises(TeamAccessDenied, match="approval unavailable"):
        teams.assign_component(OWNER_A, workspace["id"], "agent", "developer", approval_id=wrong)

    component_approval = approval(database, OWNER_A, f"team:workspace_component_change:{workspace['id']}", "COMP0001")
    teams.assign_component(OWNER_A, workspace["id"], "agent", "developer", approval_id=component_approval)
    assert teams.components(OWNER_A, workspace["id"], "agent") == ["developer"]
    with pytest.raises(TeamAccessDenied):
        teams.authorize_task(OWNER_A, workspace["id"], "developer", "github-agent")
    skill_approval = approval(database, OWNER_A, f"team:workspace_component_change:{workspace['id']}", "COMP0002")
    teams.assign_component(OWNER_A, workspace["id"], "skill", "github-agent", approval_id=skill_approval)
    teams.authorize_task(OWNER_A, workspace["id"], "developer", "github-agent")
    with pytest.raises(TeamAccessDenied, match="approval unavailable"):
        teams.assign_component(OWNER_A, workspace["id"], "agent", "qa", approval_id=component_approval)

    archive_approval = approval(database, OWNER_A, f"team:organization_archive:{organization['id']}", "ARCH0001")
    teams.archive_organization(OWNER_A, organization["id"], approval_id=archive_approval)
    with pytest.raises(TeamAccessDenied):
        teams.list_members(OWNER_A, workspace["id"])


def test_cross_workspace_and_cross_organization_access_is_blocked(tmp_path: Path) -> None:
    database, teams, audit = platform(tmp_path)
    org_a = teams.create_organization(OWNER_A, "Organization A")
    ws_a = teams.create_workspace(OWNER_A, org_a["id"], "Workspace A")
    org_b = teams.create_organization(OWNER_B, "Organization B")
    ws_b = teams.create_workspace(OWNER_B, org_b["id"], "Workspace B")
    outsider = "usr-" + "f" * 64
    invite = approval(database, OWNER_A, f"team:workspace_invite:{ws_a['id']}", "ISOLATE1")
    teams.invite(OWNER_A, ws_a["id"], "f" * 64, "Viewer", "VIEWER", approval_id=invite)
    assert teams.list_members(outsider, ws_a["id"])
    with pytest.raises(TeamAccessDenied, match="unavailable"):
        teams.list_members(outsider, ws_b["id"])
    assert teams.list_organizations(outsider)[0]["id"] == org_a["id"]
    assert org_b["id"] not in {item["id"] for item in teams.list_organizations(outsider)}
    text = (audit.root / "events.jsonl").read_text(encoding="utf-8")
    assert "SECURITY_DENIED" in text and outsider not in text


def test_knowledge_is_scoped_role_filtered_and_rejects_secrets(tmp_path: Path) -> None:
    database, teams, _ = platform(tmp_path)
    org = teams.create_organization(OWNER_A, "Knowledge Org")
    workspace = teams.create_workspace(OWNER_A, org["id"], "Knowledge")
    document = teams.add_knowledge(OWNER_A, workspace["id"], {"name": "Brand Style", "type": "markdown", "access_level": "TEAM", "content": "Use concise and friendly language."})
    assert document["content_hash"] and teams.list_knowledge(OWNER_A, workspace["id"])[0]["name"] == "Brand Style"
    with pytest.raises(TeamValidationError, match="sensitive"):
        teams.add_knowledge(OWNER_A, workspace["id"], {"name": "Bad", "type": "text", "access_level": "TEAM", "content": "password=super-secret-value"})
    with sqlite3.connect(database.path) as connection:
        raw = json.dumps(connection.execute("SELECT name,content FROM knowledge_documents").fetchall())
    assert "super-secret-value" not in raw


def test_team_tasks_comments_activity_and_viewer_restrictions(tmp_path: Path) -> None:
    database, teams, _ = platform(tmp_path)
    org = teams.create_organization(OWNER_A, "Tasks Org")
    workspace = teams.create_workspace(OWNER_A, org["id"], "Operations")
    task_id = "NX-TEAM-COMMENT"
    database.upsert_task({"task_id": task_id, "owner_namespace": OWNER_A, "title": "Team task", "status": "IN_PROGRESS", "progress": 40, "assigned_agent": "Developer", "created_at": "2026-07-21T10:00:00+00:00", "updated_at": "2026-07-21T10:00:00+00:00", "completed_at": None, "result_summary": "", "error_code": None})
    teams.link_task(OWNER_A, workspace["id"], task_id)
    comment = teams.add_comment(OWNER_A, workspace["id"], task_id, "Reviewed by the team")
    assert teams.comments(OWNER_A, workspace["id"], task_id)[0]["id"] == comment["id"]
    assert {item["event"] for item in teams.activity(OWNER_A, workspace["id"])} >= {"TASK_CREATED", "COMMENT_ADDED"}
    invite = approval(database, OWNER_A, f"team:workspace_invite:{workspace['id']}", "VIEWER01")
    teams.invite(OWNER_A, workspace["id"], "1" * 64, "Read Only", "VIEWER", approval_id=invite)
    viewer = "usr-" + "1" * 64
    assert teams.list_tasks(viewer, workspace["id"])[0]["id"] == task_id
    with pytest.raises(TeamAccessDenied):
        teams.add_comment(viewer, workspace["id"], task_id, "Not allowed")


def test_migration_006_integrity_and_rollback_preserve_v21_data(tmp_path: Path) -> None:
    database, teams, _ = platform(tmp_path)
    database.migrate()
    teams.create_organization(OWNER_A, "Rollback")
    backup = database.path.with_suffix(database.path.suffix + ".pre-v6.backup")
    assert backup.is_file()
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 5
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM templates").fetchone()[0] == 0
    database.rollback(12)
    database.rollback(11)
    database.rollback(10)
    database.rollback(9)
    database.rollback(8)
    database.rollback(7)
    database.rollback(6)
    assert database.schema_version() == 5
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='organizations'").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='templates'").fetchone()[0] == 1
