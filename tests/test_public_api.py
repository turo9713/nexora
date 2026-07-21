from __future__ import annotations

import http.client
import json
import os
import sqlite3
import threading
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


def test_versioned_http_api_task_scopes_rate_limit_and_webhook_approval(tmp_path: Path) -> None:
    server = create_server(config(tmp_path), use_tls=False)
    app = server.RequestHandlerClass.app
    _, full_key = issue(app, ["tasks:create", "tasks:read", "agents:read", "skills:read", "webhooks:manage"], "full")
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

        created_ids = []
        for index in range(10):
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
    assert specification["openapi"] == "3.1.0" and "/tasks" in specification["paths"]
