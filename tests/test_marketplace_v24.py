from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from nexora.agents.registry import AgentRegistry
from nexora.collaboration import TeamService
from nexora.database import SQLiteRepository
from nexora.integrations.telegram_runtime.services.audit_service import AuditService
from nexora.integrations.telegram_runtime.storage.audit_repository import AuditRepository
from nexora.marketplace import MarketplaceError, MarketplaceService
from nexora.marketplace.validation import PackageValidationError, PackageValidator
from nexora.security.policies import PolicyEngine


PROJECT = Path(__file__).resolve().parents[1]
OWNER = "a" * 32
OUTSIDER = "b" * 32


def platform(tmp_path: Path):
    database = SQLiteRepository(tmp_path / "state" / "nexora.sqlite3")
    database.migrate()
    agents = AgentRegistry(PROJECT / "agents").load()
    policy = PolicyEngine(agents, PROJECT, status_resolver=database.agent_enabled)
    audit_repository = AuditRepository(tmp_path / "audit")
    audit = AuditService(audit_repository, database=database)
    teams = TeamService(database, policy, audit)
    organization = teams.create_organization(OWNER, "Marketplace Organization")
    workspace = teams.create_workspace(OWNER, organization["id"], "Marketplace Workspace")
    return database, teams, MarketplaceService(database, teams, policy, audit), audit_repository, workspace


def approval(database: SQLiteRepository, owner: str, action_type: str, suffix: str) -> str:
    now = datetime.now(timezone.utc).isoformat()
    task_id = f"NX-MARKET-{suffix}"
    approval_id = f"APR-{suffix:0<8}"[:12]
    database.upsert_task({"task_id": task_id, "owner_namespace": owner, "title": "Marketplace approval", "status": "WAITING_APPROVAL", "progress": 50, "assigned_agent": "Orchestrator", "created_at": now, "updated_at": now, "completed_at": None, "result_summary": "", "error_code": None})
    database.upsert_approval({"approval_id": approval_id, "task_id": task_id, "owner_namespace": owner, "action_type": action_type, "status": "APPROVED", "expires_at": "2099-01-01T00:00:00+00:00", "used_at": now})
    return approval_id


def manifest(item_id: str, kind: str = "SKILL", risk: str = "LOW") -> dict:
    return {
        "id": item_id,
        "name": item_id.replace("-", " ").title(),
        "type": kind,
        "version": "1.0.0",
        "author": "Verified Publisher",
        "description": "Safe declarative marketplace package",
        "category": kind.casefold(),
        "permissions": {"filesystem": {"scope": "workspace"}, "network": {"mode": "none"}, "shell": False},
        "risk_level": risk,
        "requirements": [],
        "compatibility": {"minimum_nexora": "2.4.0"},
        "security": {"sandbox": True, "secret_access": False, "docker_access": False},
    }


def verified_publisher(database: SQLiteRepository, service: MarketplaceService) -> str:
    publisher = service.register_publisher(OWNER, "Verified Publisher")
    approved = approval(database, OWNER, f"marketplace:publisher_verify:{publisher['id']}", "PUBV0001")
    assert service.verify_publisher(OWNER, publisher["id"], approved)["status"] == "VERIFIED"
    with pytest.raises(MarketplaceError, match="MARKETPLACE_APPROVAL_REQUIRED"):
        service.verify_publisher(OWNER, publisher["id"], approved)
    return publisher["id"]


def test_catalog_publishers_agents_skills_templates_and_search(tmp_path: Path) -> None:
    database, _, service, _, _ = platform(tmp_path)
    pending = service.register_publisher(OUTSIDER, "Fake Publisher")
    with pytest.raises(MarketplaceError, match="MARKETPLACE_PUBLISH_DENIED"):
        service.publish(OUTSIDER, pending["id"], manifest("fake-skill"))
    publisher = verified_publisher(database, service)
    for item_id, kind in (("seo-agent", "AGENT"), ("content-optimizer", "SKILL"), ("marketing-factory", "TEMPLATE")):
        result = service.publish(OWNER, publisher, manifest(item_id, kind))
        assert result["status"] == "PUBLISHED" and result["validation_status"] == "APPROVED"
    assert {item["type"] for item in service.catalog()} == {"AGENT", "SKILL", "TEMPLATE"}
    assert service.catalog(search="optimizer")[0]["id"] == "content-optimizer"
    assert service.catalog(category="template")[0]["id"] == "marketing-factory"
    assert service.catalog(item_type="AGENT")[0]["id"] == "seo-agent"
    second = manifest("content-optimizer")
    second["version"] = "1.1.0"
    assert service.publish(OWNER, publisher, second)["version"] == "1.1.0"
    assert len(service.item("content-optimizer")["versions"]) == 2
    with pytest.raises(MarketplaceError, match="MARKETPLACE_VERSION_NOT_NEWER"):
        old = manifest("content-optimizer")
        old["version"] = "0.9.0"
        service.publish(OWNER, publisher, old)
    disabled_approval = approval(database, OWNER, "marketplace:item_status:seo-agent:DISABLED", "DISA0001")
    assert service.set_item_status(OWNER, "seo-agent", "DISABLED", approval_id=disabled_approval)["status"] == "DISABLED"
    assert not service.catalog(item_type="AGENT")


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(shell=True),
    lambda value: value.update(root=True),
    lambda value: value.update(secret_access=True),
    lambda value: value.update(docker_access=True),
    lambda value: value.update(code="print('unsafe')"),
])
def test_validation_rejects_executable_and_privilege_escalation(mutation) -> None:
    value = manifest("malicious-package")
    mutation(value)
    with pytest.raises(PackageValidationError):
        PackageValidator().validate(value)
    value = manifest("signed-package")
    with pytest.raises(PackageValidationError, match="MARKETPLACE_SIGNATURE_INVALID"):
        PackageValidator().validate(value, "sha256:deadbeef")


def test_official_example_manifests_validate_without_executable_payloads() -> None:
    results = []
    for path in sorted((PROJECT / "marketplace" / "examples").glob("*.yaml")):
        results.append(PackageValidator().validate(yaml.safe_load(path.read_text(encoding="utf-8"))).manifest)
    assert {item["type"] for item in results} == {"AGENT", "SKILL", "TEMPLATE"}
    assert all(item["security"]["sandbox"] is True and item["permissions"]["shell"] is False for item in results)
    unsigned = PackageValidator().validate(manifest("attested-package"))
    attested = PackageValidator().validate(manifest("attested-package"), f"sha256:{unsigned.checksum}")
    assert attested.signature_status == "CHECKSUM_ATTESTED"


def test_install_policy_approval_idempotency_review_and_cross_tenant_isolation(tmp_path: Path) -> None:
    database, teams, service, _, workspace = platform(tmp_path)
    publisher = verified_publisher(database, service)
    service.publish(OWNER, publisher, manifest("safe-skill"))
    low = service.install(OWNER, workspace["id"], "safe-skill")
    assert low["status"] == "ACTIVE"
    assert service.install(OWNER, workspace["id"], "safe-skill")["id"] == low["id"]
    review = service.review(OWNER, workspace["id"], "safe-skill", 5, "Useful and safe")
    assert review["rating"] == 5
    with pytest.raises(MarketplaceError, match="MARKETPLACE_REVIEW_EXISTS"):
        service.review(OWNER, workspace["id"], "safe-skill", 4, "Duplicate")

    service.publish(OWNER, publisher, manifest("medium-template", "TEMPLATE", "MEDIUM"))
    with pytest.raises(MarketplaceError, match="MARKETPLACE_APPROVAL_REQUIRED"):
        service.install(OWNER, workspace["id"], "medium-template")
    action = f"marketplace:install:{workspace['id']}:medium-template:1.0.0"
    approved = approval(database, OWNER, action, "INST0001")
    assert service.install(OWNER, workspace["id"], "medium-template", approval_id=approved)["status"] == "ACTIVE"
    outsider_org = teams.create_organization(OUTSIDER, "Other Organization")
    outsider_workspace = teams.create_workspace(OUTSIDER, outsider_org["id"], "Other Workspace")
    with pytest.raises(MarketplaceError, match="MARKETPLACE_TENANT_DENIED"):
        service.install(OUTSIDER, workspace["id"], "safe-skill")
    assert service.installations(OUTSIDER, outsider_workspace["id"]) == []


def test_checksum_tampering_and_event_immutability_fail_closed(tmp_path: Path) -> None:
    database, _, service, audit, workspace = platform(tmp_path)
    publisher = verified_publisher(database, service)
    service.publish(OWNER, publisher, manifest("tamper-test"))
    with sqlite3.connect(database.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE packages SET checksum='bad' WHERE item_id='tamper-test'")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM marketplace_events")
    package = database.get_marketplace_package("tamper-test")
    assert package is not None
    assert len(package["checksum"]) == 64
    assert "token" not in audit.path.read_text(encoding="utf-8").casefold()


def test_migration_008_backup_integrity_and_rollback(tmp_path: Path) -> None:
    database, _, service, _, _ = platform(tmp_path)
    publisher = service.register_publisher(OWNER, "Rollback Publisher")
    backup = database.path.with_suffix(database.path.suffix + ".pre-v8.backup")
    assert backup.is_file()
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 7
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert publisher["status"] == "PENDING"
    database.rollback(9)
    database.rollback(8)
    assert database.schema_version() == 7
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='marketplace_items'").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 4
