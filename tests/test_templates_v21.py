from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
import yaml

from nexora.agents.registry import AgentRegistry
from nexora.database import SQLiteRepository
from nexora.integrations.telegram_runtime.services.audit_service import AuditService
from nexora.integrations.telegram_runtime.storage.audit_repository import AuditRepository
from nexora.metrics import MetricsService
from nexora.playground import PlaygroundService
from nexora.security.policies import PolicyEngine
from nexora.skills import SkillRegistry
from nexora.templates import TemplateApprovalRequired, TemplateRegistry, TemplateValidationError
from nexora.templates.validator import TemplateValidator


PROJECT = Path(__file__).resolve().parents[1]
OWNER = "e" * 32


def platform(tmp_path: Path):
    database = SQLiteRepository(tmp_path / "state" / "nexora.sqlite3")
    database.migrate()
    agents = AgentRegistry(PROJECT / "agents").load()
    policy = PolicyEngine(agents, PROJECT, status_resolver=database.agent_enabled)
    audit_repository = AuditRepository(tmp_path / "audit")
    audit = AuditService(audit_repository, database=database)
    skills = SkillRegistry(PROJECT / "skills" / "manifests", database=database, audit=audit, agent_registry=agents, platform_version="2.1.0").load()
    metrics = MetricsService(database)
    templates = TemplateRegistry(PROJECT / "templates", database=database, agents=agents, skills=skills, policy=policy, audit=audit, metrics=metrics).load()
    return database, templates, audit_repository, metrics


def test_builtin_templates_validate_and_cannot_expand_permissions(tmp_path: Path) -> None:
    database, registry, _, _ = platform(tmp_path)
    assert registry.health() == {"ok": True, "loaded": 5, "active": 4}
    assert database.schema_version() == 5
    for item in registry.list():
        assert item["permissions"]["production"] is False
        assert item["permissions"]["level"] in {"LOW", "MEDIUM"}
        assert item["created_by"] == "Nexora"
    registry.disable("code-review", approval_id="APR-V21-DISABLE")
    assert database.get_template_status("code-review") == "DISABLED"
    registry.enable("code-review", approval_id="APR-V21-ENABLE")
    assert database.get_template_status("code-review") == "ACTIVE"


def test_template_validator_rejects_executable_and_secret_fields(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    shutil.copytree(PROJECT / "templates", root)
    source = root / "code-review" / "template.yaml"
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    raw["command"] = "whoami"
    source.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(TemplateValidationError, match="TEMPLATE_VALIDATION_FAILED"):
        TemplateValidator(root / "template.schema.json").validate_file(source)


def test_install_approval_idempotency_owner_isolation_and_rollback(tmp_path: Path) -> None:
    database, registry, audit, metrics = platform(tmp_path)
    with pytest.raises(TemplateApprovalRequired):
        registry.install(OWNER, "content-factory")
    reviewed = registry.install(OWNER, "content-factory", approval_id="APR-V21-0001")
    repeated = registry.install(OWNER, "content-factory", approval_id="APR-V21-0001")
    assert reviewed["id"] == repeated["id"] and repeated["status"] == "ACTIVE"
    other = registry.install("f" * 32, "code-review")
    assert other["id"] != reviewed["id"]
    assert len(database.list_template_installations(OWNER)) == 1
    rolled_back = registry.rollback_installation(OWNER, "content-factory", approval_id="APR-V21-0002")
    assert rolled_back["status"] == "ROLLED_BACK"
    assert metrics.community_summary(OWNER)["installed_templates"] == 0
    text = (audit.root / "events.jsonl").read_text(encoding="utf-8")
    assert "TEMPLATE_INSTALLED" in text and OWNER not in text


def test_playground_is_data_only_and_metrics_have_no_personal_data(tmp_path: Path) -> None:
    database, _, audit, metrics = platform(tmp_path)
    value = PlaygroundService(AuditService(audit, database=database)).examples()
    assert value["mode"] == "SANDBOX_ONLY"
    assert not value["external_writes"] and not value["publishing"] and not value["secrets"] and not value["production_tools"]
    metrics.demo_completed(OWNER, "article-outline")
    summary = metrics.community_summary(OWNER)
    assert summary["completed_demos"] == 1 and "owner" not in json.dumps(summary).casefold()


def test_migration_005_is_reversible_and_preserves_prior_data(tmp_path: Path) -> None:
    database, registry, _, _ = platform(tmp_path)
    registry.install(OWNER, "code-review")
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM templates").fetchone()[0] == 5
        assert connection.execute("SELECT COUNT(*) FROM skills").fetchone()[0] == 5
    database.rollback(5)
    assert database.schema_version() == 4
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM skills").fetchone()[0] == 5
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_community_structure_and_public_examples_are_complete() -> None:
    for name in ("content-agent-demo", "github-review-demo", "research-demo", "custom-skill-demo"):
        root = PROJECT / "examples" / name
        assert all((root / item).is_file() for item in ("README.md", "config.yaml", "expected-result.md"))
    for item in ("README.md", "CONTRIBUTING.md", "examples/README.md", "templates/README.md", "validation/README.md"):
        assert (PROJECT / "community-skills" / item).is_file()
