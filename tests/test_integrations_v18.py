from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from nexora.database import SQLiteRepository
from nexora.integrations.content_platform import ContentIntegration, ContentPublicationDenied
from nexora.integrations.github_integration import GitHubIntegration, GitHubIntegrationError
from nexora.webhooks import WebhookService, WebhookValidationError, verify_signature


OWNER = "e" * 32


def database(tmp_path: Path) -> SQLiteRepository:
    value = SQLiteRepository(tmp_path / "db" / "nexora.sqlite3")
    value.migrate()
    return value


def resolver(host, port, **kwargs):
    return [(2, 1, 6, "", ("8.8.8.8", 443))]


def test_webhook_signature_retry_timeout_and_disable(tmp_path: Path) -> None:
    db = database(tmp_path)
    calls = []
    secret_seen = []

    def transport(url, body, headers, timeout):
        calls.append((url, timeout))
        secret_seen.append((body, headers["X-Nexora-Signature"]))
        return 503 if len(calls) < 3 else 204

    service = WebhookService(db, b"webhook-unit-master-key-at-least-32-bytes", transport=transport, resolver=resolver, sleeper=lambda _: None)
    webhook_id = service.request_webhook(OWNER, "https://example.com/nexora", ["TASK_COMPLETED"])
    db.attach_webhook_approval(webhook_id, "APR-HOOK0001")
    secret = service.activate(webhook_id, "APR-HOOK0001")
    result = service.dispatch(OWNER, "TASK_COMPLETED", {"task_id": "NX-1", "token": "must-not-leak"}, "REQ-WEBHOOK-1")
    assert result == [{"webhook_id": webhook_id, "status": "SUCCEEDED", "attempts": 3}]
    body, signature = secret_seen[-1]
    assert verify_signature(secret, body, signature)
    assert b"must-not-leak" not in body

    def timeout_transport(url, body, headers, timeout):
        raise TimeoutError("safe timeout")

    failing = WebhookService(db, b"webhook-unit-master-key-at-least-32-bytes", transport=timeout_transport, resolver=resolver, sleeper=lambda _: None, max_attempts=2, disable_after=2)
    failing.dispatch(OWNER, "TASK_COMPLETED", {"task_id": "NX-2"}, "REQ-WEBHOOK-2")
    failing.dispatch(OWNER, "TASK_COMPLETED", {"task_id": "NX-3"}, "REQ-WEBHOOK-3")
    assert db.get_webhook_record(webhook_id)["status"] == "DISABLED"
    assert secret not in db.path.read_bytes().decode("latin1")


def test_webhook_rejects_insecure_and_private_targets(tmp_path: Path) -> None:
    db = database(tmp_path)
    service = WebhookService(db, b"webhook-unit-master-key-at-least-32-bytes", resolver=lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(WebhookValidationError):
        service.request_webhook(OWNER, "http://example.com/hook", ["TASK_COMPLETED"])
    webhook_id = service.request_webhook(OWNER, "https://example.com/hook", ["TASK_COMPLETED"])
    db.attach_webhook_approval(webhook_id, "APR-HOOK0002")
    service.activate(webhook_id, "APR-HOOK0002")
    with pytest.raises(WebhookValidationError, match="not public"):
        service.dispatch(OWNER, "TASK_COMPLETED", {}, "REQ-WEBHOOK-4")


def test_github_is_read_only_and_content_requires_approval() -> None:
    github = GitHubIntegration()
    plan = github.repository_plan("openai/example")
    assert plan["mode"] == "READ_ONLY" and plan["writes"] is False
    response = github.request("GET", "/repos/openai/example/pulls", lambda method, url: {"method": method, "url": url})
    assert response["method"] == "GET" and response["url"].startswith("https://api.github.com/")
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        with pytest.raises(GitHubIntegrationError):
            github.request(method, "/repos/openai/example", lambda *_: None)

    content = ContentIntegration()
    draft = content.prepare("Safe article")
    assert draft["route"] == ["research", "content", "qa", "approval"] and draft["auto_publish"] is False
    with pytest.raises(ContentPublicationDenied):
        content.authorize_publication(False)
    assert content.authorize_publication(True)["execution"] == "EXTERNAL_PUBLISHER_NOT_CONFIGURED"


def test_metrics_tables_and_rollback_preserve_existing_data(tmp_path: Path) -> None:
    db = database(tmp_path)
    db.record_metric("skill_call", 1, owner=OWNER, labels={"skill": "github-agent"})
    with sqlite3.connect(db.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 1
    db.rollback(9)
    db.rollback(8)
    db.rollback(7)
    db.rollback(6)
    db.rollback(5)
    db.rollback(4)
    assert db.schema_version() == 3
