from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path

import pytest

from nexora.dashboard.backend.server import COOKIE_NAME, DashboardRequestHandler
from nexora.storage import ArtifactError, ArtifactRepository

from .conftest import NAMESPACE, ORIGIN, PASSWORD


def completed_task(app, result: str = "Safe artifact result") -> tuple[dict, dict]:
    workspace = app.api.teams.list_workspaces(NAMESPACE)[0]
    context = app.api.teams.workspace_context(NAMESPACE, workspace["id"], "tasks:create")
    task = app.api.tasks.create(
        NAMESPACE,
        "Artifact smoke task",
        "artifact-session",
        workspace_context={**context, "workspace_id": workspace["id"]},
    )
    app.api.tasks.update_fields(NAMESPACE, task["task_id"], result_summary=result)
    task = app.api.tasks.transition(NAMESPACE, task["task_id"], "COMPLETED")
    return workspace, task


def request(connection, method, path, *, body=None, cookie=None, csrf=None):
    headers = {"Origin": ORIGIN, "Accept": "application/json"}
    payload = None
    if body is not None:
        payload = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = f"{COOKIE_NAME}={cookie}"
    if csrf:
        headers["X-CSRF-Token"] = csrf
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    return response, raw


def test_completed_task_creates_private_checksum_verified_artifacts(dashboard_factory) -> None:
    app, _ = dashboard_factory()
    workspace, task = completed_task(app, "Report token=fixture-artifact-secret")

    result = app.api.list_artifacts({"workspace_id": workspace["id"]})
    assert {item["kind"] for item in result["items"]} == {"markdown", "json"}
    assert all(item["task_id"] == task["task_id"] for item in result["items"])
    assert all("owner" not in item and "storage_name" not in item for item in result["items"])

    for item in result["items"]:
        details = app.api.artifact_details(item["id"], {"workspace_id": workspace["id"]})
        metadata, payload = app.api.artifacts.download(NAMESPACE, item["id"])
        assert details["checksum_sha256"] == hashlib.sha256(payload).hexdigest()
        assert details["size_bytes"] == len(payload)
        assert "fixture-artifact-secret" not in details["preview"]
        assert metadata["workspace_id"] == workspace["id"]

    task_details = app.api.task_details(task["task_id"])
    assert len(task_details["artifacts"]) == 2
    audit = app.api.database.list_audit(event="ARTIFACT_CREATED", limit=20)
    assert len(audit) == 2

    root = app.api.artifacts.repository.root
    if os.name == "posix":
        assert (root.stat().st_mode & 0o777) == 0o700
        for path in root.rglob("*"):
            if path.is_dir():
                assert (path.stat().st_mode & 0o777) == 0o700
            elif path.is_file():
                assert (path.stat().st_mode & 0o777) == 0o600


def test_artifact_repository_is_idempotent_scoped_and_blocks_symlink_escape(tmp_path: Path) -> None:
    repository = ArtifactRepository(tmp_path / "artifacts")
    values = {
        "owner": NAMESPACE,
        "workspace_id": "WS-ARTIFACT01",
        "task_id": "NX-ARTIFACT-001",
        "title": "Result",
        "kind": "markdown",
        "content": b"# Safe result\n",
    }
    first = repository.create(**values)
    second = repository.create(**values)
    assert first["id"] == second["id"]
    assert len(repository.list(NAMESPACE, "WS-ARTIFACT01")) == 1
    assert repository.list("c" * 32, "WS-ARTIFACT01") == []

    with pytest.raises(ArtifactError):
        repository.create(**{**values, "kind": "executable"})
    with pytest.raises(ArtifactError):
        repository.create(**{**values, "task_id": "../../escape"})

    if os.name == "posix":
        outside = tmp_path / "outside"
        outside.mkdir()
        owner_path = repository.root / ("d" * 32)
        owner_path.symlink_to(outside, target_is_directory=True)
        with pytest.raises(RuntimeError):
            repository.create(**{**values, "owner": "d" * 32})


def test_artifact_http_requires_auth_workspace_and_serves_safe_content_type(dashboard_factory) -> None:
    app, _ = dashboard_factory()
    workspace, _ = completed_task(app)
    artifact = app.api.list_artifacts({"workspace_id": workspace["id"]})["items"][0]

    class Handler(DashboardRequestHandler):
        pass

    Handler.app = app
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response, raw = request(connection, "GET", f"/api/artifacts?workspace_id={workspace['id']}")
        assert response.status == 401
        assert json.loads(raw)["error"] == "UNAUTHORIZED"

        response, raw = request(connection, "POST", "/api/login", body={"username": "admin", "password": PASSWORD})
        assert response.status == 200
        login = json.loads(raw)
        cookie = response.getheader("Set-Cookie").split(";", 1)[0].split("=", 1)[1]

        response, raw = request(connection, "GET", f"/api/artifacts?workspace_id={workspace['id']}", cookie=cookie)
        assert response.status == 200 and len(json.loads(raw)["items"]) == 2
        response, raw = request(
            connection,
            "GET",
            f"/api/artifacts/{artifact['id']}?workspace_id=WS-NOT-AVAILABLE",
            cookie=cookie,
        )
        assert response.status == 404 and json.loads(raw)["error"] == "WORKSPACE_NOT_FOUND"

        response, raw = request(
            connection,
            "GET",
            f"/api/artifacts/{artifact['id']}/download?workspace_id={workspace['id']}",
            cookie=cookie,
        )
        assert response.status == 200
        assert response.getheader("Content-Disposition").startswith("attachment;")
        assert response.getheader("Content-Type") in {
            "text/markdown; charset=utf-8",
            "application/json; charset=utf-8",
        }
        assert raw
        assert app.api.database.list_audit(event="ARTIFACT_DOWNLOADED", limit=10)
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_artifact_frontend_is_read_only_and_uses_workspace_scope() -> None:
    project = Path(__file__).resolve().parents[2]
    script = (project / "dashboard" / "frontend" / "app.js").read_text(encoding="utf-8")
    index = (project / "dashboard" / "frontend" / "index.html").read_text(encoding="utf-8")
    permissions = (project / "dashboard" / "permissions" / "service.py").read_text(encoding="utf-8")

    assert 'data-route="/artifacts"' in index
    assert "async function artifactsPage" in script
    assert "/api/artifacts?" in script
    assert "/download?workspace_id=" in script
    assert '"artifacts:read"' in permissions
    artifact_ui = script[script.index("async function artifactsPage"):script.index("async function agentsPage")]
    assert 'method:"POST"' not in artifact_ui
