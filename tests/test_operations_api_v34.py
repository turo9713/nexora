from __future__ import annotations

import http.client
import json
import os
import threading
from pathlib import Path

from nexora.api.gateway.server import PublicAPIConfig, create_server


PROJECT = Path(__file__).resolve().parents[1]
OWNER = "1" * 32
FOREIGN = "2" * 32


def config(tmp_path: Path) -> PublicAPIConfig:
    secret = tmp_path / "api-master"
    secret.write_bytes(b"operations-api-test-master-key-32-bytes")
    os.chmod(secret, 0o600)
    return PublicAPIConfig(
        host="127.0.0.1", port=0, project_root=PROJECT,
        state_root=tmp_path / "state" / "telegram_v14",
        database_path=tmp_path / "state" / "database" / "nexora.sqlite3",
        webhook_master_file=secret, agent_memory_key_file=secret,
        tls_cert_file=None, tls_key_file=None,
    )


def issue(app, scopes: list[str], name: str) -> str:
    key_id = app.keys.request_key(OWNER, name, scopes, "2099-01-01T00:00:00+00:00")
    approval_id = "APR-OPSAPI01"
    app.gateway.database.attach_api_key_approval(key_id, approval_id)
    return app.keys.activate(key_id, approval_id)


def request(connection, path: str, key: str | None = None):
    headers = {"Accept": "application/json", "X-Request-ID": "REQ-OPS-V34", "X-Correlation-ID": "CORR-OPS-V34"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    connection.request("GET", path, headers=headers)
    response = connection.getresponse()
    return response, json.loads(response.read())


def test_public_operations_api_auth_scopes_tenant_isolation_and_audit(tmp_path: Path) -> None:
    server = create_server(config(tmp_path), use_tls=False)
    app = server.RequestHandlerClass.app
    organization = app.gateway.teams.create_organization(OWNER, "Operations API Organization")
    workspace = app.gateway.teams.create_workspace(OWNER, organization["id"], "Operations API Workspace")
    app.gateway.database.set_workspace_component(workspace["id"], "agent", "developer", True)
    task = {
        "task_id": "NX-OPS-API-001", "owner_namespace": OWNER, "title": "Operations API task",
        "status": "COMPLETED", "progress": 100, "assigned_agent": "developer",
        "created_at": "2026-07-22T08:00:00+00:00", "updated_at": "2026-07-22T08:01:00+00:00",
        "completed_at": "2026-07-22T08:01:00+00:00", "result_summary": "safe", "error_code": None,
    }
    app.gateway.database.upsert_task(task)
    app.gateway.teams.link_task(OWNER, workspace["id"], task["task_id"])
    app.gateway.database.insert_task_event({
        "event_id": "EVT-OPS-API-COMPLETE", "task_id": task["task_id"], "type": "TASK_COMPLETED",
        "metadata": {"status": "COMPLETED", "token": "do-not-return"}, "timestamp": "2026-07-22T08:01:00+00:00",
    })
    foreign_org = app.gateway.teams.create_organization(FOREIGN, "Foreign Operations Organization")
    foreign_workspace = app.gateway.teams.create_workspace(FOREIGN, foreign_org["id"], "Foreign Operations Workspace")

    operations_key = issue(app, ["operations:read"], "operations")
    notifications_key = issue(app, ["notifications:read"], "notifications")
    agents_key = issue(app, ["agents:read"], "agent-status")
    wrong_key = issue(app, ["tasks:read"], "wrong-scope")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        response, data = request(connection, "/api/v1/dashboard")
        assert response.status == 401 and data["error"] == "UNAUTHORIZED"
        response, data = request(connection, "/api/v1/dashboard", wrong_key)
        assert response.status == 403 and data["error"] == "SCOPE_DENIED"

        query = f"?workspace_id={workspace['id']}"
        response, dashboard = request(connection, "/api/v1/dashboard" + query, operations_key)
        assert response.status == 200 and dashboard["workspace"]["id"] == workspace["id"]
        assert response.getheader("X-Request-ID") == "REQ-OPS-V34"
        assert response.getheader("X-Correlation-ID") == "CORR-OPS-V34"
        response, activity = request(connection, "/api/v1/activity" + query, operations_key)
        assert response.status == 200 and activity["items"]
        response, notifications = request(connection, "/api/v1/notifications" + query, notifications_key)
        assert response.status == 200 and notifications["items"][0]["type"] == "TASK_COMPLETED"
        response, agents = request(connection, "/api/v1/agents/status" + query, agents_key)
        assert response.status == 200 and agents["items"][0]["id"] == "developer"

        response, data = request(connection, f"/api/v1/dashboard?workspace_id={foreign_workspace['id']}", operations_key)
        assert response.status == 404 and data["error"] == "WORKSPACE_NOT_FOUND"
        serialized = json.dumps({"dashboard": dashboard, "activity": activity, "notifications": notifications, "agents": agents})
        assert "do-not-return" not in serialized and FOREIGN not in serialized

        audit = (config(tmp_path).state_root / "audit" / "events.jsonl").read_text(encoding="utf-8")
        assert "API_REQUEST" in audit and "API_SUCCESS" in audit and "API_DENIED" in audit
        assert operations_key not in audit and notifications_key not in audit and "Authorization" not in audit
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
