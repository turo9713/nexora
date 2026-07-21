from __future__ import annotations

import http.client
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from nexora.api.auth import APIKeyService
from nexora.api.gateway.server import PublicAPIConfig, create_application, create_server
from nexora.api.rate_limit import APIRateLimiter


PROJECT = Path(__file__).resolve().parents[1]
OWNER = "d" * 32


def config(tmp_path: Path) -> PublicAPIConfig:
    master = tmp_path / "webhook_master"
    master.write_bytes(b"public-api-test-webhook-master-key-32-bytes")
    os.chmod(master, 0o600)
    return PublicAPIConfig(
        host="127.0.0.1",
        port=0,
        project_root=PROJECT,
        state_root=tmp_path / "state" / "telegram_v14",
        database_path=tmp_path / "state" / "database" / "nexora.sqlite3",
        webhook_master_file=master,
        tls_cert_file=None,
        tls_key_file=None,
    )


def issue(app, scopes: list[str], name: str = "test") -> tuple[str, str]:
    key_id = app.keys.request_key(OWNER, name, scopes, "2099-01-01T00:00:00+00:00")
    approval_id = "APR-TEST0001"
    app.gateway.database.attach_api_key_approval(key_id, approval_id)
    return key_id, app.keys.activate(key_id, approval_id)


def request(connection, method: str, path: str, *, key: str | None = None, body: dict | None = None):
    headers = {"Accept": "application/json", "X-Correlation-ID": "CORR-TEST-0001"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload = None
    if body is not None:
        payload = json.dumps(body)
        headers["Content-Type"] = "application/json"
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    data = json.loads(response.read())
    return response, data


def marketplace_approval(database, owner: str, action_type: str) -> str:
    now = datetime.now(timezone.utc).isoformat()
    approval_id = "APR-MARKET01"
    database.upsert_task({"task_id": "NX-MARKET-API", "owner_namespace": owner, "title": "Marketplace approval", "status": "WAITING_APPROVAL", "progress": 50, "assigned_agent": "Orchestrator", "created_at": now, "updated_at": now, "completed_at": None, "result_summary": "", "error_code": None})
    database.upsert_approval({"approval_id": approval_id, "task_id": "NX-MARKET-API", "owner_namespace": owner, "action_type": action_type, "status": "APPROVED", "expires_at": "2099-01-01T00:00:00+00:00", "used_at": now})
    return approval_id


def test_api_key_hash_scope_invalid_and_expired(tmp_path: Path) -> None:
    app = create_application(config(tmp_path))
    key_id, plaintext = issue(app, ["tasks:read"])
    record = app.gateway.database.get_api_key_record(key_id)
    assert record is not None and record["key_hash"].startswith("scrypt$")
    assert plaintext not in json.dumps(record)
    assert app.keys.authenticate(plaintext, "tasks:read") is not None
    assert app.keys.authenticate(plaintext, "tasks:create") is None
    assert app.keys.authenticate("nx_live_deadbeefdead_invalid-invalid-invalid-invalid") is None

    with sqlite3.connect(app.gateway.database.path) as connection:
        connection.execute("UPDATE api_keys SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (key_id,))
    assert app.keys.authenticate(plaintext, "tasks:read") is None
    audit_text = (config(tmp_path).state_root / "audit" / "events.jsonl")
    if audit_text.exists():
        assert plaintext not in audit_text.read_text(encoding="utf-8")


def test_rate_limit_per_key_endpoint_owner_and_recovery() -> None:
    now = [100.0]
    limiter = APIRateLimiter(clock=lambda: now[0])
    assert limiter.allow("KEY-A", OWNER, "/api/v1/tasks", limit=2)
    assert limiter.allow("KEY-A", OWNER, "/api/v1/tasks", limit=2)
    assert not limiter.allow("KEY-A", OWNER, "/api/v1/tasks", limit=2)
    assert not limiter.allow("KEY-B", OWNER, "/api/v1/tasks", limit=2)
    assert limiter.allow("KEY-A", OWNER, "/api/v1/skills", limit=2)
    now[0] += 61
    assert limiter.allow("KEY-A", OWNER, "/api/v1/tasks", limit=2)


def test_marketplace_http_api_scopes_publish_catalog_and_install(tmp_path: Path) -> None:
    server = create_server(config(tmp_path), use_tls=False)
    app = server.RequestHandlerClass.app
    organization = app.gateway.teams.create_organization(OWNER, "Marketplace API Organization")
    workspace = app.gateway.teams.create_workspace(OWNER, organization["id"], "Marketplace API Workspace")
    publisher = app.gateway.marketplace.register_publisher(OWNER, "API Publisher")
    approved = marketplace_approval(app.gateway.database, OWNER, f"marketplace:publisher_verify:{publisher['id']}")
    app.gateway.marketplace.verify_publisher(OWNER, publisher["id"], approved)
    _, key = issue(app, ["marketplace:read", "marketplace:publish", "marketplace:install"], "marketplace")
    _, read_key = issue(app, ["marketplace:read"], "marketplace-read")
    manifest = {
        "id": "api-market-skill", "name": "API Market Skill", "type": "SKILL", "version": "1.0.0",
        "author": "API Publisher", "description": "Safe API package", "category": "skills",
        "permissions": {"filesystem": {"scope": "workspace"}, "network": {"mode": "none"}, "shell": False},
        "risk_level": "LOW", "requirements": [], "compatibility": {"minimum_nexora": "2.4.0"},
        "security": {"sandbox": True, "secret_access": False, "docker_access": False},
    }
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        response, data = request(connection, "POST", "/api/v1/marketplace/publish", key=read_key, body={"publisher_id": publisher["id"], "manifest": manifest})
        assert response.status == 403 and data["error"] == "SCOPE_DENIED"
        response, data = request(connection, "POST", "/api/v1/marketplace/publish", key=key, body={"publisher_id": publisher["id"], "manifest": manifest})
        assert response.status == 201 and data["id"] == "api-market-skill"
        response, data = request(connection, "GET", "/api/v1/marketplace?type=SKILL", key=key)
        assert response.status == 200 and data["items"][0]["id"] == "api-market-skill"
        response, data = request(connection, "GET", "/api/v1/marketplace/api-market-skill", key=key)
        assert response.status == 200 and data["manifest"]["security"]["sandbox"] is True
        response, data = request(connection, "POST", "/api/v1/marketplace/api-market-skill/install", key=key, body={"workspace_id": workspace["id"]})
        assert response.status == 201 and data["status"] == "ACTIVE"
        response, data = request(connection, "POST", "/api/v1/marketplace/api-market-skill/install", key=read_key, body={"workspace_id": workspace["id"]})
        assert response.status == 403 and data["error"] == "SCOPE_DENIED"
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
def test_versioned_http_api_task_scopes_rate_limit_and_webhook_approval(tmp_path: Path) -> None:
    server = create_server(config(tmp_path), use_tls=False)
    app = server.RequestHandlerClass.app
    organization = app.gateway.teams.create_organization(OWNER, "API Test Organization")
    _, full_key = issue(app, ["tasks:create", "tasks:read", "agents:read", "skills:read", "templates:read", "templates:install", "playground:read", "webhooks:manage", "organizations:read", "workspaces:read", "workspaces:write", "members:read", "knowledge:read", "knowledge:write", "plans:read", "billing:read", "usage:read", "limits:read"], "full")
    _, read_key = issue(app, ["tasks:read"], "read-only")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        response, data = request(connection, "GET", "/healthz")
        assert response.status == 200 and data["status"] == "ok"
        response, data = request(connection, "GET", "/api/v1/tasks", key="invalid")
        assert response.status == 401 and data["error"] == "UNAUTHORIZED"
        response, data = request(connection, "POST", "/api/v1/tasks", key=read_key, body={"title": "Denied", "agent": "developer", "skill": "github-agent"})
        assert response.status == 403 and data["error"] == "SCOPE_DENIED"

        foreign_owner = "e" * 32
        foreign_org = app.gateway.teams.create_organization(foreign_owner, "Foreign Organization")
        foreign_workspace = app.gateway.teams.create_workspace(foreign_owner, foreign_org["id"], "Foreign Workspace")
        before = len(app.gateway.database.list_tasks(OWNER, limit=100))
        response, data = request(connection, "POST", "/api/v1/tasks", key=full_key, body={"title": "Foreign tenant", "agent": "developer", "skill": "github-agent", "workspace_id": foreign_workspace["id"]})
        assert response.status == 404 and data["error"] == "WORKSPACE_NOT_FOUND"
        assert len(app.gateway.database.list_tasks(OWNER, limit=100)) == before

        created_ids = []
        for index in range(9):
            response, data = request(connection, "POST", "/api/v1/tasks", key=full_key, body={"title": f"Analyze repository {index}", "agent": "developer", "skill": "github-agent"})
            assert response.status == 202 and data["status"] == "QUEUED"
            created_ids.append(data["task_id"])
        response, data = request(connection, "POST", "/api/v1/tasks", key=full_key, body={"title": "Over limit", "agent": "developer", "skill": "github-agent"})
        assert response.status == 429 and data["error"] == "RATE_LIMIT_EXCEEDED"

        response, data = request(connection, "GET", f"/api/v1/tasks/{created_ids[0]}", key=full_key)
        assert response.status == 200 and data["task_id"] == created_ids[0]
        response, data = request(connection, "GET", "/api/v1/agents", key=full_key)
        assert response.status == 200 and any(item["id"] == "developer" for item in data["items"])
        response, data = request(connection, "GET", "/api/v1/skills", key=full_key)
        assert response.status == 200 and any(item["id"] == "github-agent" for item in data["items"])
        response, data = request(connection, "GET", "/api/v1/templates", key=full_key)
        assert response.status == 200 and any(item["id"] == "content-factory" for item in data["items"])
        response, data = request(connection, "GET", "/api/v1/templates/code-review", key=full_key)
        assert response.status == 200 and data["permissions"]["production"] is False
        response, data = request(connection, "POST", "/api/v1/templates/code-review", key=full_key, body={})
        assert response.status == 202 and data["status"] == "ACTIVE"
        response, data = request(connection, "POST", "/api/v1/templates/content-factory", key=full_key, body={})
        assert response.status == 202 and data["status"] == "WAITING_APPROVAL"
        response, data = request(connection, "GET", "/api/v1/playground/examples", key=full_key)
        assert response.status == 200 and data["mode"] == "SANDBOX_ONLY" and data["external_writes"] is False
        response, data = request(connection, "GET", "/api/v1/templates", key=read_key)
        assert response.status == 403 and data["error"] == "SCOPE_DENIED"
        response, data = request(connection, "GET", "/api/v1/organizations", key=full_key)
        assert response.status == 200 and data["items"][0]["id"] == organization["id"]
        response, workspace = request(connection, "POST", "/api/v1/workspaces", key=full_key, body={"organization_id": organization["id"], "name": "API Workspace", "description": "Scoped"})
        assert response.status == 201 and workspace["organization_id"] == organization["id"]
        response, data = request(connection, "GET", f"/api/v1/members?workspace_id={workspace['id']}", key=full_key)
        assert response.status == 200 and data["items"][0]["role"] == "OWNER"
        response, data = request(connection, "POST", "/api/v1/invite", key=full_key, body={"workspace_id": workspace["id"]})
        assert response.status == 403 and data["error"] == "SCOPE_DENIED"
        response, document = request(connection, "POST", "/api/v1/knowledge", key=full_key, body={"workspace_id": workspace["id"], "name": "API Guide", "type": "markdown", "access_level": "TEAM", "content": "Safe team instructions"})
        assert response.status == 201 and document["workspace_id"] == workspace["id"]
        response, data = request(connection, "GET", f"/api/v1/knowledge?workspace_id={workspace['id']}", key=full_key)
        assert response.status == 200 and data["items"][0]["name"] == "API Guide"
        response, data = request(connection, "GET", "/api/v1/plans", key=full_key)
        assert response.status == 200 and [item["id"] for item in data["items"]] == ["free", "pro", "team", "enterprise"]
        response, data = request(connection, "GET", f"/api/v1/subscription?organization_id={organization['id']}", key=full_key)
        assert response.status == 200 and data["plan_id"] == "free"
        response, data = request(connection, "POST", "/api/v1/subscription", key=full_key, body={"plan_id": "enterprise"})
        assert response.status == 404 and data["error"] == "NOT_FOUND"
        response, data = request(connection, "GET", f"/api/v1/usage?organization_id={organization['id']}", key=full_key)
        assert response.status == 200 and data["events"]["documents"] == 1
        response, data = request(connection, "POST", "/api/v1/usage", key=full_key, body={"metric": "tasks_created", "value": -1000})
        assert response.status == 404 and data["error"] == "NOT_FOUND"
        response, data = request(connection, "GET", f"/api/v1/limits?organization_id={organization['id']}", key=full_key)
        assert response.status == 200 and data["limits"]["workspace_limit"] == 1
        response, data = request(connection, "GET", f"/api/v1/usage?organization_id={foreign_org['id']}", key=full_key)
        assert response.status == 404 and data["error"] == "ORGANIZATION_NOT_FOUND"
        response, data = request(connection, "GET", "/api/v1/plans", key=read_key)
        assert response.status == 403 and data["error"] == "SCOPE_DENIED"
        response, data = request(connection, "POST", "/api/v1/webhooks", key=full_key, body={"url": "https://example.com/nexora", "events": ["TASK_COMPLETED"]})
        assert response.status == 202 and data["status"] == "WAITING_APPROVAL"
        assert "secret" not in json.dumps(data).casefold()

        audit = (config(tmp_path).state_root / "audit" / "events.jsonl").read_text(encoding="utf-8")
        assert "API_REQUEST" in audit and "API_SUCCESS" in audit and "API_DENIED" in audit and "API_RATE_LIMITED" in audit
        assert full_key not in audit and read_key not in audit and "Authorization" not in audit
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_public_api_has_no_gateway_transport_or_secret_config(tmp_path: Path) -> None:
    value = PublicAPIConfig()
    assert not hasattr(value, "gateway_token") and not hasattr(value, "gateway_url")
    source = (PROJECT / "api" / "gateway" / "server.py").read_text(encoding="utf-8").casefold()
    assert "openclaw_provider" not in source and "openclaw_transport" not in source
    specification = yaml.safe_load((PROJECT / "api" / "schemas" / "openapi-v1.yaml").read_text(encoding="utf-8"))
    assert specification["openapi"] == "3.1.0" and "/tasks" in specification["paths"] and "/templates" in specification["paths"]
    assert {"/organizations", "/workspaces", "/members", "/invite", "/knowledge", "/plans", "/subscription", "/usage", "/limits"}.issubset(specification["paths"])
