from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nexora.integrations.telegram_runtime.security.access_control import AccessControl
from nexora.integrations.telegram_runtime.security.callback_validation import parse_approval_callback
from nexora.integrations.telegram_runtime.security.redaction import redact_text, safe_error_code
from nexora.integrations.telegram_runtime.services.approval_service import ApprovalService
from nexora.integrations.telegram_runtime.services.idempotency_service import IdempotencyService
from nexora.integrations.telegram_runtime.services.progress_service import ProgressService
from nexora.integrations.telegram_runtime.services.task_service import TaskService
from nexora.integrations.telegram_runtime.storage.action_repository import ActionRepository
from nexora.integrations.telegram_runtime.storage.approval_repository import ApprovalRepository
from nexora.integrations.telegram_runtime.storage.context_repository import ContextRepository
from nexora.integrations.telegram_runtime.storage.task_repository import TaskRepository

from .conftest import NAMESPACE_KEY, OWNER_ID, callback_update, owner_message


def test_access_control_owner_message_and_namespace():
    access = AccessControl(OWNER_ID, NAMESPACE_KEY)
    assert access.is_owner_message(owner_message(1, "/status"))
    assert len(access.owner_namespace) == 32
    assert str(OWNER_ID) not in access.owner_namespace


def test_access_control_rejects_unknown_message():
    access = AccessControl(OWNER_ID, NAMESPACE_KEY)
    assert not access.is_owner_message(owner_message(1, "/status", owner_id=999))


def test_access_control_rejects_unknown_callback():
    access = AccessControl(OWNER_ID, NAMESPACE_KEY)
    assert not access.is_owner_callback(callback_update(1, "apr:approve:APR-1234ABCD", owner_id=999))


@pytest.mark.parametrize(
    "payload",
    [
        "Authorization: Bearer abc.def",
        "api_key=secret-value",
        "password=hunter2",
        "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_12345",
        "postgres://user:pass@example/db",
        "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----",
    ],
)
def test_redaction_removes_sensitive_values(payload: str):
    redacted = redact_text(payload)
    assert payload != redacted
    assert "hunter2" not in redacted
    assert "secret-value" not in redacted


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (TimeoutError("timed out"), "NX_TIMEOUT"),
        (RuntimeError("provider transport failed"), "NX_PROVIDER_ERROR"),
        (ValueError("schema validation failed"), "NX_VALIDATION_ERROR"),
        (PermissionError("denied"), "NX_PERMISSION_DENIED"),
        (RuntimeError("cancelled"), "NX_TASK_CANCELLED"),
        (RuntimeError("unexpected"), "NX_INTERNAL_ERROR"),
    ],
)
def test_safe_error_codes(error: Exception, code: str):
    assert safe_error_code(error) == code


def test_callback_validation_accepts_only_short_approval_id():
    assert parse_approval_callback("apr:approve:APR-1234ABCD") == ("approve", "APR-1234ABCD")
    assert parse_approval_callback("apr:approve:APR-1234ABCD;rm -rf") is None


def test_progress_service_validates_integer_range():
    service = ProgressService()
    task = {"progress": 0, "transitions": []}
    assert service.transition(task, "COMPLETED")["progress"] == 100
    with pytest.raises(ValueError):
        service.transition(task, "IN_PROGRESS", progress=101)


def test_task_repository_isolates_namespaces(tmp_path: Path):
    repository = TaskRepository(tmp_path / "tasks")
    service = TaskService(repository)
    first = "a" * 32
    second = "b" * 32
    task = service.create(first, "Owner task", "session")
    assert service.get(first, task["task_id"]) is not None
    assert service.get(second, task["task_id"]) is None


def test_task_history_limit(tmp_path: Path):
    service = TaskService(TaskRepository(tmp_path / "tasks"))
    namespace = "a" * 32
    for index in range(12):
        service.create(namespace, f"Task {index}", "session")
    assert len(service.history(namespace, 10)) == 10


def test_context_permissions_and_no_identity(tmp_path: Path):
    store = ContextRepository(root=tmp_path / "context")
    session = store.new()
    session = store.set_active_task(session, "NX-TEST-123")
    session = store.add_turn(session, "user", "safe message")
    store.save(session)
    if os.name == "posix":
        assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    raw = store.path.read_text(encoding="utf-8")
    assert "telegram_id" not in raw and "owner_id" not in raw and str(OWNER_ID) not in raw


def test_corrupt_context_is_failed_closed(tmp_path: Path):
    store = ContextRepository(root=tmp_path / "context")
    store.root.mkdir(parents=True)
    store.path.write_text("{broken", encoding="utf-8")
    assert store.load() is None
    assert not store.path.exists()


def test_corrupt_task_record_is_not_returned(tmp_path: Path):
    repository = TaskRepository(tmp_path / "tasks")
    namespace = "a" * 32
    path = repository._path(namespace, "NX-TEST-123")
    path.write_text("not-json", encoding="utf-8")
    assert repository.get(namespace, "NX-TEST-123") is None


def test_approval_is_one_time(tmp_path: Path):
    service = ApprovalService(ApprovalRepository(tmp_path / "approvals"))
    namespace = "a" * 32
    approval = service.create(namespace, "NX-TEST-123", "session", "restart", "Restart", "Risk")
    status, _ = service.decide(namespace, approval["approval_id"], "session", "approve")
    repeated, _ = service.decide(namespace, approval["approval_id"], "session", "approve")
    assert status == "APPROVED" and repeated == "ALREADY_USED"


def test_approval_rejection_does_not_approve(tmp_path: Path):
    service = ApprovalService(ApprovalRepository(tmp_path / "approvals"))
    namespace = "a" * 32
    approval = service.create(namespace, "NX-TEST-123", "session", "restart", "Restart", "Risk")
    status, saved = service.decide(namespace, approval["approval_id"], "session", "reject")
    assert status == "REJECTED" and saved["status"] == "REJECTED"


def test_approval_expiration(tmp_path: Path):
    repository = ApprovalRepository(tmp_path / "approvals")
    service = ApprovalService(repository)
    namespace = "a" * 32
    approval = service.create(namespace, "NX-TEST-123", "session", "restart", "Restart", "Risk")
    approval["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    repository.save(namespace, approval)
    status, _ = service.decide(namespace, approval["approval_id"], "session", "approve")
    assert status == "EXPIRED"


def test_approval_session_isolation(tmp_path: Path):
    service = ApprovalService(ApprovalRepository(tmp_path / "approvals"))
    namespace = "a" * 32
    approval = service.create(namespace, "NX-TEST-123", "session-a", "restart", "Restart", "Risk")
    status, _ = service.decide(namespace, approval["approval_id"], "session-b", "approve")
    assert status == "NOT_FOUND"


def test_approval_invalidation(tmp_path: Path):
    service = ApprovalService(ApprovalRepository(tmp_path / "approvals"))
    namespace = "a" * 32
    approval = service.create(namespace, "NX-TEST-123", "session", "restart", "Restart", "Risk")
    assert service.invalidate_task(namespace, "NX-TEST-123") == 1
    assert service.repository.get(namespace, approval["approval_id"])["status"] == "INVALIDATED"


def test_idempotency_blocks_duplicate_action(tmp_path: Path):
    namespace = "a" * 32
    service = IdempotencyService(ActionRepository(tmp_path / "actions"))
    assert service.begin(namespace, "same-key", "test")
    assert not service.begin(namespace, "same-key", "test")
    service.set_status(namespace, "same-key", "SUCCEEDED")
    assert service.succeeded(namespace, "same-key")


def test_action_file_permissions(tmp_path: Path):
    namespace = "a" * 32
    repository = ActionRepository(tmp_path / "actions")
    service = IdempotencyService(repository)
    service.begin(namespace, "key", "test")
    action_files = list((tmp_path / "actions" / namespace).glob("*.json"))
    assert len(action_files) == 1
    if os.name == "posix":
        assert stat.S_IMODE(action_files[0].stat().st_mode) == 0o600
        assert stat.S_IMODE(action_files[0].parent.stat().st_mode) == 0o700
