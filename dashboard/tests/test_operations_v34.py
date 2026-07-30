from __future__ import annotations

import http.client
import json
import threading

from nexora.dashboard.backend.server import COOKIE_NAME, DashboardRequestHandler

from .conftest import NAMESPACE, ORIGIN, PASSWORD, PROJECT


def request(connection, method, path, *, body=None, cookie=None, csrf=None):
    headers = {"Origin": ORIGIN, "Accept": "application/json"}
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
    return response, json.loads(raw) if raw else {}


def completed_workspace_task(app):
    workspace = app.api.list_workspaces({})["items"][0]
    app.api.database.set_workspace_component(workspace["id"], "agent", "developer", True)
    task = app.api.tasks.create(NAMESPACE, "Operations dashboard smoke", "ops-v34", "NX-OPS-DASH-001")
    app.api.teams.link_task(NAMESPACE, workspace["id"], task["task_id"])
    app.api.tasks.transition(NAMESPACE, task["task_id"], "IN_PROGRESS", stage="Выполнение", progress=40)
    app.api.tasks.transition(NAMESPACE, task["task_id"], "COMPLETED", stage="Готово", progress=100)
    return workspace, task


def test_dashboard_operations_services_and_realtime_projection(dashboard_factory) -> None:
    app, _ = dashboard_factory()
    workspace, task = completed_workspace_task(app)

    home = app.api.user_dashboard({"workspace_id": workspace["id"]})
    assert home["workspace"]["name"] == workspace["name"]
    assert home["completed_tasks"] == 1 and home["unread_notifications"] == 1
    assert home["realtime_cursor"]

    activity = app.api.activity_feed({"workspace_id": workspace["id"]})["items"]
    assert {item["type"] for item in activity} >= {"TASK_CREATED", "TASK_COMPLETED"}
    assert all("metadata" not in item and "owner" not in item for item in activity)

    notifications = app.api.notifications_feed({"workspace_id": workspace["id"]})
    assert notifications["unread"] == 1
    notification_id = notifications["items"][0]["id"]
    assert app.api.mark_notification_read(notification_id, {"workspace_id": workspace["id"]})["status"] == "READ"

    agent_status = app.api.agent_status_center({"workspace_id": workspace["id"]})["items"]
    assert [item["id"] for item in agent_status] == ["developer"]
    assert agent_status[0]["status"] == "IDLE"
    analytics = app.api.operations_analytics({"workspace_id": workspace["id"]})
    assert analytics["tasks"]["created"] == 1 and analytics["tasks"]["success_rate"] == 100.0
    realtime = app.api.realtime_events({"workspace_id": workspace["id"]})["items"]
    assert realtime[-1]["type"] == "TASK_COMPLETED" and realtime[-1]["task_id"] == task["task_id"]


def test_dashboard_operations_http_auth_csrf_audit_and_safe_surfaces(dashboard_factory) -> None:
    app, _ = dashboard_factory()
    workspace, _ = completed_workspace_task(app)

    class Handler(DashboardRequestHandler):
        pass

    Handler.app = app
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        for path in ("/api/dashboard", "/api/activity", "/api/notifications", "/api/workspace-overview", "/api/agents/status", "/api/operations/analytics", "/api/realtime/tasks"):
            response, data = request(connection, "GET", path)
            assert response.status == 401 and data["error"] == "UNAUTHORIZED"

        response, data = request(connection, "POST", "/api/login", body={"username": "admin", "password": PASSWORD})
        assert response.status == 200
        cookie = response.getheader("Set-Cookie").split(";", 1)[0].split("=", 1)[1]
        csrf = data["csrf_token"]
        query = f"?workspace_id={workspace['id']}"
        expected = {
            "/api/dashboard": "workspace",
            "/api/activity": "items",
            "/api/notifications": "items",
            "/api/workspace-overview": "name",
            "/api/agents/status": "items",
            "/api/operations/analytics": "tasks",
        }
        values = {}
        for path, field in expected.items():
            response, payload = request(connection, "GET", path + query, cookie=cookie)
            assert response.status == 200 and field in payload
            values[path] = payload

        notification_id = values["/api/notifications"]["items"][0]["id"]
        read_path = f"/api/notifications/{notification_id}/read{query}"
        response, data = request(connection, "POST", read_path, body={}, cookie=cookie)
        assert response.status == 403 and data["error"] == "CSRF_DENIED"
        response, data = request(connection, "POST", read_path, body={}, cookie=cookie, csrf=csrf)
        assert response.status == 200 and data["status"] == "READ"

        audit = json.dumps(app.api.database.list_audit(event="API_ACCESS"), ensure_ascii=False)
        assert "/api/dashboard" in audit and "/api/agents/status" in audit and "/api/notifications" in audit
        assert cookie not in audit and "Authorization" not in audit
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_v34_frontend_is_event_driven_and_has_no_tool_or_task_mutation() -> None:
    script = (PROJECT / "dashboard" / "frontend" / "app.js").read_text(encoding="utf-8")
    index = (PROJECT / "dashboard" / "frontend" / "index.html").read_text(encoding="utf-8")
    server = (PROJECT / "dashboard" / "backend" / "server.py").read_text(encoding="utf-8")
    for route in ("/home", "/activity", "/notifications", "/workspace", "/agents/status", "/analytics", "/onboarding"):
        assert route in script or route in index
    assert "new EventSource" in script and "TASK_PROGRESS_UPDATED" in script and "onerror" in script
    assert "initializeNotificationCenter" in script
    assert "scheduleNotificationRefresh" in script
    assert 'api(`/api/notifications?workspace_id=' in script
    assert 'data.unread' in script
    assert "tasksPageV342Base" in script and "taskPageV342Base" in script
    assert "event.lastEventId" in script and "realtimeSeen" in script
    assert 'dataset.realtimeFallback="true"' in script
    assert 'card("Workflows"' in script and "data.workflows.items" in script
    assert "setInterval(" not in script
    assert "/api/realtime/tasks" in server and "text/event-stream" in server
    assert 'api("/api/tasks",{method:"POST"' not in script
    assert "/tools" not in script and "openclaw" not in script.casefold()
