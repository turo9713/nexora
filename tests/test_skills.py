from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from nexora.agents.registry import AgentRegistry
from nexora.database import SQLiteRepository
from nexora.integrations.telegram_runtime.services.audit_service import AuditService
from nexora.integrations.telegram_runtime.storage.audit_repository import AuditRepository
from nexora.skills import SkillRegistry, SkillRegistryError
from nexora.skills.loader import SkillLoader
from nexora.skills.policies import SkillPolicyEngine
from nexora.skills.validators import SkillManifestValidator, SkillValidationError
from nexora.security.policies import PolicyEngine


PROJECT = Path(__file__).resolve().parents[1]


def registry(tmp_path: Path) -> tuple[SkillRegistry, SQLiteRepository, AuditRepository]:
    manifests = tmp_path / "manifests"
    shutil.copytree(PROJECT / "skills" / "manifests", manifests)
    database = SQLiteRepository(tmp_path / "state" / "nexora.sqlite3")
    database.migrate()
    audit_repository = AuditRepository(tmp_path / "audit")
    audit = AuditService(audit_repository, database=database)
    agents = AgentRegistry(PROJECT / "agents").load()
    skills = SkillRegistry(manifests, database=database, audit=audit, agent_registry=agents).load()
    return skills, database, audit_repository


def test_registry_lifecycle_enable_disable_remove(tmp_path: Path) -> None:
    skills, database, audit = registry(tmp_path)
    assert skills.health() == {"ok": True, "loaded": 18, "active": 3}
    assert skills.require_active("content-writer").agent == "content"
    skills.disable("content-writer", approval_id="APR-TEST0001")
    assert database.get_skill_status("content-writer") == "DISABLED"
    with pytest.raises(SkillRegistryError):
        skills.require_active("content-writer")
    skills.enable("content-writer", approval_id="APR-TEST0002")
    assert database.get_skill_status("content-writer") == "ACTIVE"
    skills.remove("analytics", approval_id="APR-TEST0003")
    assert database.get_skill_status("analytics") == "REMOVED"
    assert skills.get("analytics") is None
    audit_text = audit.path.read_text(encoding="utf-8")
    assert "SKILL_DISABLED" in audit_text and "SKILL_ENABLED" in audit_text and "SKILL_REMOVED" in audit_text


def test_validator_rejects_invalid_missing_schema_and_forbidden_permissions(tmp_path: Path) -> None:
    manifests = tmp_path / "manifests"
    shutil.copytree(PROJECT / "skills" / "manifests", manifests)
    validator = SkillManifestValidator(manifests / "skill.schema.json")
    valid = validator.validate_file(manifests / "content-writer.yaml")
    assert valid["id"] == "content-writer"

    invalid = yaml.safe_load((manifests / "content-writer.yaml").read_text(encoding="utf-8"))
    invalid["permissions"]["shell"]["enabled"] = True
    invalid_path = manifests / "invalid.yaml"
    invalid_path.write_text(yaml.safe_dump(invalid), encoding="utf-8")
    with pytest.raises(SkillValidationError, match="SKILL_VALIDATION_FAILED"):
        validator.validate_file(invalid_path)

    invalid["permissions"]["shell"]["enabled"] = False
    invalid["entrypoint"] = "/bin/sh"
    invalid_path.write_text(yaml.safe_dump(invalid), encoding="utf-8")
    with pytest.raises(SkillValidationError, match="SKILL_VALIDATION_FAILED"):
        validator.validate_file(invalid_path)

    (manifests / "skill.schema.json").unlink()
    with pytest.raises(SkillValidationError, match="schema unavailable"):
        validator.validate_file(manifests / "content-writer.yaml")


def test_loader_is_metadata_only_and_policy_is_scoped(tmp_path: Path) -> None:
    skills, _, _ = registry(tmp_path)
    agents = AgentRegistry(PROJECT / "agents").load()
    loader = SkillLoader(
        skills,
        SkillPolicyEngine(Path("/workspace/nexora")),
        PolicyEngine(agents, Path("/workspace/nexora")),
    )
    activation = loader.activate(
        "content-writer",
        agent_id="content",
        tool="text_generation",
        path="drafts/article.md",
    )
    assert activation.status == "ACTIVE" and activation.tools == ("text_generation",)
    with pytest.raises(PermissionError, match="path_outside_skill_scope"):
        loader.activate("content-writer", agent_id="content", path=".env")
    with pytest.raises(PermissionError, match="agent_mismatch"):
        loader.activate("content-writer", agent_id="devops")
    with pytest.raises(SkillRegistryError):
        loader.activate("unknown", agent_id="content")
    with pytest.raises(PermissionError, match="approval_required"):
        loader.activate("research", agent_id="research", tool="research", path="docs/skills.md", network_mode="search_only")
    approved = loader.activate(
        "research",
        agent_id="research",
        tool="research",
        path="docs/skills.md",
        network_mode="search_only",
        approval_granted=True,
    )
    assert approved.skill_id == "research"


def test_skill_database_migration_is_reversible(tmp_path: Path) -> None:
    skills, database, _ = registry(tmp_path)
    assert database.schema_version() == 13
    assert len(database.list_skills()) == 18
    details = database.get_skill_details("research")
    assert details is not None and details["permission_rows"]
    database.rollback(13)
    database.rollback(12)
    database.rollback(11)
    database.rollback(10)
    database.rollback(9)
    database.rollback(8)
    database.rollback(7)
    database.rollback(6)
    database.rollback(5)
    database.rollback(4)
    assert database.schema_version() == 3
    assert database.path.exists()


def test_skill_manifests_do_not_contain_secret_or_execution_fields() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in (PROJECT / "skills" / "manifests").glob("*.yaml"))
    lowered = text.casefold()
    for forbidden in ("entrypoint", "docker.sock", "/run/secrets", "telegram_token", "api_key", "shell:\n  enabled: true"):
        assert forbidden not in lowered
    assert json.loads((PROJECT / "skills" / "manifests" / "skill.schema.json").read_text(encoding="utf-8"))


def test_reviewed_skills_are_read_only_and_disabled_by_default(tmp_path: Path) -> None:
    skills, _, _ = registry(tmp_path)
    reviewed = {
        "secure-code-review",
        "runtime-testing-patterns",
        "e2e-testing-patterns",
        "technical-documentation",
        "diagram-maker",
        "markdown-authoring",
        "project-documentation",
        "api-design-review",
        "python-quality",
        "threat-modeling",
        "database-design-review",
        "architecture-review",
        "accessibility-review",
    }
    for skill_id in reviewed:
        manifest = skills.require(skill_id)
        assert manifest.default_status == "DISABLED"
        assert manifest.permissions["filesystem"]["mode"] == "read_only"
        assert manifest.permissions["network"]["mode"] == "none"
        assert manifest.permissions["shell"]["enabled"] is False
        assert manifest.permissions["production"]["enabled"] is False
        assert manifest.sandbox_enabled is True

    expected_agents = {
        "technical-documentation": "developer",
        "runtime-testing-patterns": "qa",
        "e2e-testing-patterns": "qa",
        "diagram-maker": "developer",
        "markdown-authoring": "content",
    }
    for skill_id, agent_id in expected_agents.items():
        assert skills.require(skill_id).agent == agent_id
