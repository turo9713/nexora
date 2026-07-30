from __future__ import annotations

import http.client
import json
import threading

from nexora.dashboard.backend.server import COOKIE_NAME, DashboardRequestHandler
from nexora.skills.registry.registry import BUILTIN_SKILLS

from .conftest import ORIGIN, PASSWORD


def request(connection, method, path, *, body=None, cookie=None, csrf=None, origin=ORIGIN):
    headers = {"Origin": origin, "Accept": "application/json"}
    payload = None
    if body is not None:
        payload = json.dumps(body)
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = f"{COOKIE_NAME}={cookie}"
    if csrf:
        headers["X-CSRF-Token"] = csrf
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    data = json.loads(raw) if raw else {}
    return response, data


def test_authenticated_http_api_csrf_headers_and_logout(dashboard_factory) -> None:
    app, config = dashboard_factory()
    task = app.api.tasks.create("b" * 32, "HTTP Task Control Center", "http-read-session", "NX-HTTP-READ-001")
    app.api.tasks.transition("b" * 32, task["task_id"], "COMPLETED", event="HTTP_READ_READY")

    class Handler(DashboardRequestHandler):
        pass

    Handler.app = app
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        response, data = request(connection, "GET", "/api/health")
        assert response.status == 401 and data["error"] == "UNAUTHORIZED"
        response, data = request(connection, "GET", "/api/agents")
        assert response.status == 401 and data["error"] == "UNAUTHORIZED"
        response, data = request(connection, "GET", "/api/tasks")
        assert response.status == 401 and data["error"] == "UNAUTHORIZED"
        response, data = request(connection, "GET", "/api/queue")
        assert response.status == 401 and data["error"] == "UNAUTHORIZED"
        response, data = request(connection, "GET", "/api/tasks/NX-HTTP-READ-001/events")
        assert response.status == 401 and data["error"] == "UNAUTHORIZED"

        response, _ = request(connection, "POST", "/api/login", body={"username": "admin", "password": "wrong-password-value"})
        assert response.status == 401

        response, data = request(connection, "POST", "/api/login", body={"username": "admin", "password": PASSWORD})
        assert response.status == 200
        cookie_header = response.getheader("Set-Cookie")
        assert cookie_header and "Secure" in cookie_header and "HttpOnly" in cookie_header and "SameSite=Strict" in cookie_header
        cookie = cookie_header.split(";", 1)[0].split("=", 1)[1]
        csrf = data["csrf_token"]

        response, data = request(connection, "GET", "/api/health", cookie=cookie)
        assert response.status == 200 and data["database"] == "OK"
        assert data["skills"]["loaded"] == len(BUILTIN_SKILLS)
        assert response.getheader("Content-Security-Policy")
        assert response.getheader("X-Frame-Options") == "DENY"

        response, data = request(connection, "GET", "/api/skills", cookie=cookie)
        assert response.status == 200 and len(data["items"]) == len(BUILTIN_SKILLS)

        response, data = request(connection, "GET", "/api/agents", cookie=cookie)
        assert response.status == 200 and len(data["items"]) == 8
        assert {"description", "risk_level", "allowed_tools", "completed_tasks", "last_activity"} <= set(data["items"][0])
        response, data = request(connection, "GET", "/api/agents/developer", cookie=cookie)
        assert response.status == 200 and data["id"] == "developer"
        response, data = request(connection, "POST", "/api/agents/developer/actions", body={"action": "disable"}, cookie=cookie, csrf=csrf)
        assert response.status == 403 and data["error"] == "FORBIDDEN"
        assert app.api.database.get_agent_override("developer") is None
        agent_audit = json.dumps(app.api.database.list_audit(event="API_ACCESS"))
        assert "/api/agents" in agent_audit
        assert cookie not in agent_audit and "Authorization" not in agent_audit

        response, data = request(connection, "GET", "/api/tasks", cookie=cookie)
        assert response.status == 200 and data["items"][0]["task_id"] == "NX-HTTP-READ-001"
        response, data = request(connection, "GET", "/api/tasks/NX-HTTP-READ-001", cookie=cookie)
        assert response.status == 200 and data["task_id"] == "NX-HTTP-READ-001"
        response, data = request(connection, "GET", "/api/tasks/NX-HTTP-READ-001/events", cookie=cookie)
        assert response.status == 200 and data["items"][-1]["type"] == "TASK_COMPLETED"
        response, missing = request(connection, "GET", "/api/tasks/NX-NOT-AVAILABLE", cookie=cookie)
        assert response.status == 404 and missing["error"] == "TASK_NOT_FOUND"
        workspace = app.api._dashboard_workspace_context({})
        queued_task = app.api.tasks.create(
            "b" * 32,
            "Queue visibility",
            "queue-session",
            "NX-HTTP-QUEUE-001",
            workspace_context=workspace,
        )
        app.api.database.enqueue_execution_job(
            owner="b" * 32,
            task_id=queued_task["task_id"],
            session_id="queue-session",
            worker_group="dashboard",
            idempotency_key="http-queue-test",
            priority=7,
        )
        response, queue = request(connection, "GET", f"/api/queue?workspace_id={workspace['workspace_id']}", cookie=cookie)
        assert response.status == 200 and queue["summary"]["queued"] == 1
        assert queue["items"][0]["task_id"] == queued_task["task_id"]
        assert "session_id" not in queue["items"][0] and "idempotency_key" not in queue["items"][0]
        task_audit = json.dumps(app.api.database.list_audit(event="API_ACCESS"))
        assert "/api/tasks/NX-HTTP-READ-001/events" in task_audit
        assert "/api/queue" in task_audit
        assert cookie not in task_audit and "Authorization" not in task_audit

        response, data = request(connection, "GET", "/api/platform/metrics", cookie=cookie)
        assert response.status == 200 and "tasks_today" in data
        response, data = request(connection, "POST", "/api/platform/api-keys", body={"name": "HTTP test", "scopes": ["tasks:read"]}, cookie=cookie)
        assert response.status == 403 and data["error"] == "CSRF_DENIED"
        response, data = request(connection, "POST", "/api/platform/api-keys", body={"name": "HTTP test", "scopes": ["tasks:read"]}, cookie=cookie, csrf=csrf)
        assert response.status == 202 and data["status"] == "WAITING_APPROVAL"
        response, data = request(connection, "GET", "/api/skills/content-writer", cookie=cookie)
        assert response.status == 200 and data["sandbox"] is True
        response, data = request(connection, "POST", "/api/skills/content-writer/disable", body={}, cookie=cookie)
        assert response.status == 403 and data["error"] == "CSRF_DENIED"
        response, data = request(connection, "POST", "/api/skills/content-writer/disable", body={}, cookie=cookie, csrf=csrf)
        assert response.status == 202 and data["status"] == "WAITING_APPROVAL"

        response, data = request(connection, "POST", "/api/logout", body={}, cookie=cookie)
        assert response.status == 403 and data["error"] == "CSRF_DENIED"
        response, data = request(connection, "POST", "/api/logout", body={}, cookie=cookie, csrf=csrf)
        assert response.status == 200 and data["status"] == "LOGGED_OUT"
        response, _ = request(connection, "GET", "/api/health", cookie=cookie)
        assert response.status == 401
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
