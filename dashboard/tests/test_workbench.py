from __future__ import annotations

import os
import http.client
import json
import threading
import time
from pathlib import Path

import pytest

from nexora.dashboard.api import DashboardAPIError
from nexora.dashboard.runtime import DashboardTaskRuntime
from nexora.dashboard.backend.server import COOKIE_NAME, DashboardRequestHandler

from .conftest import NAMESPACE, ORIGIN, PASSWORD


class FakeOrchestrator:
    def run_task(self, task: dict, workflow_name: str) -> dict:
        latest = str(task["description"]).split("OWNER:")[-1].strip()
        text = f"WEB_OK: {latest}"
        return {
            "result": {
                "summary": text,
                "details": {
                    "transport_response": {
                        "response": {"output": [{"content": [{"type": "output_text", "text": text}]}]}
                    }
                },
            }
        }


def attach_runtime(app, config, orchestrator=None) -> DashboardTaskRuntime:
    runtime = DashboardTaskRuntime(
        orchestrator or FakeOrchestrator(),
        app.api.tasks,
        app.api.approvals,
        app.api.audit,
        app.api.policy,
        config.state_root,
    )
    app.api.task_runtime = runtime
    return runtime


def wait_for(app, task_id: str, status: str = "COMPLETED") -> dict:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        stored = app.api.database.get_task_details(NAMESPACE, task_id)
        if stored and stored.get("status") == status:
            return app.api.tasks.get(NAMESPACE, task_id) or stored
        time.sleep(0.02)
    raise AssertionError(f"task did not reach {status}")


def test_workbench_home_exposes_honest_agent_routing_and_history_filters() -> None:
    script = (Path(__file__).resolve().parents[1] / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'api("/api/agents")' in script
    assert "Автоподбор агента" in script
    assert "Orchestrator назначает агента автоматически" in script
    assert '["all","Все"]' in script
    assert '["active","В работе"]' in script
    assert '["completed","Готовые"]' in script


def test_global_quick_task_uses_existing_protected_workbench_contract() -> None:
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    script = (frontend / "app.js").read_text(encoding="utf-8")
    index = (frontend / "index.html").read_text(encoding="utf-8")

    assert 'id="quick-task-toggle"' in index
    assert 'id="quick-task-modal"' in index
    assert 'id="quick-task-message"' in index
    assert 'api("/api/workbench/tasks"' in script
    assert "workspace_id:state.notificationWorkspace" in script
    assert 'idempotency_key:requestKey("quick-task")' in script
    quick_task = script[script.index("function closeQuickTask"):script.index('el("login-form")')]
    assert "agent_id" not in quick_task


def test_dashboard_create_continue_idempotency_and_safe_download(dashboard_factory) -> None:
    app, config = dashboard_factory()
    runtime = attach_runtime(app, config)
    first = app.api.create_dashboard_task({"message": "Составь безопасный план", "idempotency_key": "request-0001"})
    repeated = app.api.create_dashboard_task({"message": "Не должно дублироваться", "idempotency_key": "request-0001"})
    assert repeated["id"] == first["id"]
    completed = wait_for(app, first["id"])
    assert completed["result_summary"].startswith("WEB_OK")

    continued = app.api.continue_dashboard_task(
        first["id"],
        {"message": "Продолжи и не показывай token=fixture-super-secret", "idempotency_key": "message-0001"},
    )
    assert continued["id"] == first["id"]
    completed = wait_for(app, first["id"])
    assert completed["turn_number"] == 2
    details = app.api.task_details(first["id"])
    assert len(runtime.conversation(first["id"])) == 4
    assert "conversation" not in details
    assert "fixture-super-secret" not in str(details)
    assert details["downloads"][0]["id"] == "result"
    filename, payload = app.api.task_result_file(first["id"])
    assert filename.endswith("-result.txt") and b"WEB_OK" in payload
    assert b"fixture-super-secret" not in payload

    context_root = config.state_root / "dashboard_sessions"
    assert context_root.is_dir() and not context_root.is_symlink()
    assert (context_root / "active.json").is_file() and not (context_root / "active.json").is_symlink()
    if os.name != "nt":
        assert os.stat(context_root).st_mode & 0o777 == 0o700
        assert os.stat(context_root / "active.json").st_mode & 0o777 == 0o600
    runtime.execution.shutdown()


def test_dashboard_policy_approval_and_cancel(dashboard_factory) -> None:
    app, config = dashboard_factory()
    runtime = attach_runtime(app, config)
    pending = app.api.create_dashboard_task({"message": "restart service safely", "idempotency_key": "approval-0001"})
    assert pending["status"] == "WAITING_APPROVAL"
    approval_id = app.api.tasks.get(NAMESPACE, pending["id"])["pending_approval_id"]
    approved = app.api.decide_approval(approval_id, "approve")
    assert approved["execution"] == "QUEUED"
    wait_for(app, pending["id"])

    next_task = app.api.create_dashboard_task({"message": "Новая безопасная задача", "idempotency_key": "cancel-0001"})
    cancelled = app.api.cancel_dashboard_task(next_task["id"])
    assert cancelled["status"] in {"CANCELLED", "COMPLETED"}
    runtime.execution.shutdown()


def test_dashboard_runtime_rejects_forbidden_and_cross_task_access(dashboard_factory) -> None:
    app, config = dashboard_factory()
    runtime = attach_runtime(app, config)
    with pytest.raises(DashboardAPIError) as denied:
        app.api.create_dashboard_task({"message": "rm -rf /", "idempotency_key": "denied-0001"})
    assert denied.value.code == "NX_PERMISSION_DENIED"
    with pytest.raises(DashboardAPIError) as missing:
        app.api.continue_dashboard_task("NX-NOT-AVAILABLE", {"message": "test", "idempotency_key": "missing-0001"})
    assert missing.value.code == "NX_TASK_NOT_FOUND"
    runtime.execution.shutdown()


def test_dashboard_task_control_center_http_is_read_only(dashboard_factory) -> None:
    app, config = dashboard_factory()
    runtime = attach_runtime(app, config)
    created = app.api.create_dashboard_task({"message": "HTTP read-only task", "idempotency_key": "http-0001"})
    wait_for(app, created["id"])

    class Handler(DashboardRequestHandler):
        pass

    Handler.app = app
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)

    def call(method: str, path: str, body=None, cookie=None, csrf=None):
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

    try:
        response, login = call("POST", "/api/login", {"username": "admin", "password": PASSWORD})
        assert response.status == 200
        cookie = response.getheader("Set-Cookie").split(";", 1)[0].split("=", 1)[1]
        response, listed = call("GET", "/api/tasks", cookie=cookie)
        assert response.status == 200 and listed["items"][0]["task_id"] == created["id"]
        response, details = call("GET", f"/api/tasks/{created['id']}", cookie=cookie)
        assert response.status == 200 and details["status"] == "COMPLETED"
        response, timeline = call("GET", f"/api/tasks/{created['id']}/events", cookie=cookie)
        assert response.status == 200 and any(item["type"] == "TASK_COMPLETED" for item in timeline["items"])

        before = app.api.database.get_task_details(NAMESPACE, created["id"])
        for path, body in (
            ("/api/tasks", {"message": "must not run", "idempotency_key": "http-denied"}),
            (f"/api/tasks/{created['id']}/messages", {"message": "must not continue", "idempotency_key": "http-denied-message"}),
            (f"/api/tasks/{created['id']}/cancel", {}),
        ):
            response, denied = call("POST", path, body, cookie, login["csrf_token"])
            assert response.status == 403 and denied["error"] == "FORBIDDEN"
        after = app.api.database.get_task_details(NAMESPACE, created["id"])
        assert after == before

        connection.request("GET", f"/api/tasks/{created['id']}/downloads/result", headers={"Origin": ORIGIN, "Cookie": f"{COOKIE_NAME}={cookie}"})
        response = connection.getresponse()
        payload = response.read()
        assert response.status == 200 and response.getheader("Content-Disposition").startswith("attachment;")
        assert b"WEB_OK" in payload
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        runtime.execution.shutdown()


def test_authenticated_workbench_http_runs_workspace_scoped_task(dashboard_factory) -> None:
    app, config = dashboard_factory()
    runtime = attach_runtime(app, config)

    class Handler(DashboardRequestHandler):
        pass

    Handler.app = app
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)

    def call(method: str, path: str, body=None, cookie=None, csrf=None):
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

    try:
        denied, _ = call(
            "POST",
            "/api/workbench/tasks",
            {"message": "must be denied", "idempotency_key": "anonymous-request"},
        )
        assert denied.status == 401

        response, login = call("POST", "/api/login", {"username": "admin", "password": PASSWORD})
        assert response.status == 200
        cookie = response.getheader("Set-Cookie").split(";", 1)[0].split("=", 1)[1]
        workspace_id = app.api.list_workspaces({})["items"][0]["id"]
        payload = {
            "message": "Create a safe workbench plan",
            "workspace_id": workspace_id,
            "idempotency_key": "workbench-http-0001",
        }
        response, denied_workspace = call(
            "POST",
            "/api/workbench/tasks",
            {**payload, "workspace_id": "WS-NOT-AVAILABLE", "idempotency_key": "workbench-cross-tenant"},
            cookie,
            login["csrf_token"],
        )
        assert response.status == 400
        assert denied_workspace["error"] == "NX_WORKSPACE_REQUIRED"
        response, created = call("POST", "/api/workbench/tasks", payload, cookie, login["csrf_token"])
        assert response.status == 202
        task_id = created["id"]
        completed = wait_for(app, task_id)
        assert completed["workspace_id"] == workspace_id
        assert completed["organization_id"]

        response, repeated = call("POST", "/api/workbench/tasks", payload, cookie, login["csrf_token"])
        assert response.status in {201, 202}
        assert repeated["id"] == task_id

        response, continued = call(
            "POST",
            f"/api/workbench/tasks/{task_id}/messages",
            {
                "message": "Add one implementation milestone",
                "workspace_id": workspace_id,
                "idempotency_key": "workbench-http-message-0001",
            },
            cookie,
            login["csrf_token"],
        )
        assert response.status == 202 and continued["id"] == task_id
        assert wait_for(app, task_id)["turn_number"] == 2

        response, details = call("GET", f"/api/tasks/{task_id}", cookie=cookie)
        assert response.status == 200
        assert details["status"] == "COMPLETED"
        assert "WEB_OK" in details["result_summary"]
        assert any(
            item["event"] == "DASHBOARD_TASK_CREATED"
            for item in app.api.database.list_audit(event="DASHBOARD_TASK_CREATED", limit=100)
        )
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        runtime.execution.shutdown()
