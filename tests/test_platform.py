from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from nexora.agents.registry import AgentRegistry, REQUIRED_AGENTS
from nexora.database import SQLiteRepository
from nexora.integrations.telegram_runtime.handlers import TelegramRuntimeHandlers
from nexora.integrations.telegram_runtime.services.audit_service import AuditService
from nexora.integrations.telegram_runtime.storage.audit_repository import AuditRepository
from nexora.runtime.events import EventBus, SQLiteEventSink
from nexora.security.policies import PolicyEngine


PROJECT = Path(__file__).resolve().parents[1]
NAMESPACE = "a" * 32


class FakeWorkflows:
    def load_workflow(self, name: str) -> dict[str, Any]:
        return {"status": "LOADED", "route": ["orchestrator", "developer", "qa", "owner"]}


class NoLLMOrchestrator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.workflows = FakeWorkflows()

    def run_task(self, task: dict[str, Any], workflow_name: str) -> dict[str, Any]:
        self.calls.append(task)
        raise AssertionError("LLM must not be called by /health")


def message(update_id: int, user_id: int, text: str) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "from": {"id": user_id},
            "chat": {"id": user_id, "type": "private"},
            "text": text,
        },
    }


def sample_task(task_id: str = "NX-20260721-ABCDEF") -> dict[str, Any]:
    return {
        "task_id": task_id,
        "owner_namespace": NAMESPACE,
        "title": "Safe task",
        "status": "COMPLETED",
        "progress": 100,
        "assigned_agent": "Developer",
        "created_at": "2026-07-21T08:00:00+00:00",
        "updated_at": "2026-07-21T08:01:00+00:00",
        "completed_at": "2026-07-21T08:01:00+00:00",
        "result_summary": "Done",
        "error_code": None,
    }


def test_agent_registry_loads_all_manifests() -> None:
    registry = AgentRegistry(PROJECT / "agents").load()
    assert tuple(manifest.id for manifest in registry.all()) == REQUIRED_AGENTS
    assert registry.health() == {"ok": True, "loaded": 8, "enabled": 8}
    for manifest in registry.all():
        assert manifest.system_role
        assert manifest.permissions
        assert manifest.tools_allowed
        assert manifest.restrictions


def test_policy_is_fail_closed_and_workspace_scoped() -> None:
    registry = AgentRegistry(PROJECT / "agents").load()
    policy = PolicyEngine(registry, Path("/workspace/nexora"))
    assert policy.evaluate("unknown").allowed is False
    assert policy.evaluate("developer", tool="shell").allowed is False
    assert policy.evaluate("developer", tool="read", path="/etc/passwd").allowed is False
    assert policy.evaluate("developer", tool="read", path="docs/security.md").allowed is True
    approval = policy.evaluate("developer", risk="HIGH")
    assert approval.allowed is False and approval.requires_approval is True
    assert policy.evaluate("developer", risk="HIGH", approval_granted=True).allowed is True
    assert policy.evaluate("developer", action_type="secrets_access", approval_granted=True).allowed is False


def test_database_migration_import_and_rollback_preserve_json(tmp_path: Path) -> None:
    state = tmp_path / "state" / "tasks" / NAMESPACE
    state.mkdir(parents=True)
    source = state / "NX-20260721-ABCDEF.json"
    source.write_text(json.dumps(sample_task()), encoding="utf-8")
    database = SQLiteRepository(tmp_path / "database" / "nexora.sqlite3")
    assert database.migrate() == 9
    assert database.import_task_directory(state.parent) == 1
    assert database.check() is True
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    assert source.exists()
    assert oct(database.path.parent.stat().st_mode & 0o777) == "0o700"
    assert oct(database.path.stat().st_mode & 0o777) == "0o600"
    database.rollback(9)
    database.rollback(8)
    database.rollback(7)
    database.rollback(6)
    database.rollback(5)
    database.rollback(4)
    assert database.schema_version() == 3
    database.rollback(3)
    assert database.schema_version() == 2
    database.rollback(2)
    assert database.schema_version() == 1
    database.rollback(1)
    assert database.schema_version() == 0
    assert source.exists()


def test_events_and_audit_redact_sensitive_metadata(tmp_path: Path) -> None:
    database = SQLiteRepository(tmp_path / "db" / "nexora.sqlite3")
    database.migrate()
    database.upsert_task(sample_task())
    bus = EventBus([SQLiteEventSink(database)])
    event = bus.publish(
        "TASK_COMPLETED",
        task_id="NX-20260721-ABCDEF",
        metadata={
            "status": "COMPLETED",
            "telegram_id": "9988776655",
            "context": "private conversation",
            "authorization": "Bearer fixture-secret-value",
            "safe": "visible",
        },
    )
    serialized = json.dumps(event, ensure_ascii=False)
    assert "9988776655" not in serialized
    assert "private conversation" not in serialized
    assert "fixture-secret-value" not in serialized
    assert event["metadata"] == {"status": "COMPLETED", "safe": "visible"}

    audit_repository = AuditRepository(tmp_path / "audit")
    audit = AuditService(audit_repository, database=database)
    audit.record(
        "SECURITY_DENIED",
        authorization="Bearer another-fixture-secret",
        telegram_id="1122334455",
        reason="allowlist",
    )
    audit_text = audit_repository.path.read_text(encoding="utf-8")
    assert "another-fixture-secret" not in audit_text
    assert "1122334455" not in audit_text
    record = json.loads(audit_text)
    assert record["severity"] == "SECURITY"
    assert len(record["hash"]) == 64


def test_health_is_owner_only_and_does_not_call_llm(tmp_path: Path) -> None:
    orchestrator = NoLLMOrchestrator()
    owner_id = 100
    context_path = tmp_path / "context"
    handler = TelegramRuntimeHandlers(
        owner_id=owner_id,
        namespace_key=b"platform-test-namespace-key-at-least-32-bytes",
        orchestrator=orchestrator,
        state_path=tmp_path / "state",
        context_path=context_path,
    )
    try:
        owner_response = handler.handle_update(message(1, owner_id, "/health"))
        assert owner_response is not None
        assert owner_response.text is not None and "Nexora Health" in owner_response.text
        assert "Database: OK" in owner_response.text
        assert "Agents: 8 loaded" in owner_response.text
        assert orchestrator.calls == []

        denied = handler.handle_update(message(2, 999, "/health"))
        assert denied is not None and denied.text == "ACCESS_DENIED"
        assert not context_path.exists()
        assert orchestrator.calls == []
        database_bytes = handler.database.path.read_bytes()
        assert b"9988776655" not in database_bytes
    finally:
        handler.close()


def test_gitignore_covers_sensitive_runtime_data() -> None:
    rules = (PROJECT / ".gitignore").read_text(encoding="utf-8")
    for required in (".env", "secrets/", "runtime/state/", "*.sqlite3", "*.log", ".venv/"):
        assert required in rules
