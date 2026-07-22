from __future__ import annotations

import json

from nexora.operations.realtime import RealtimeService

from .conftest import FakeOrchestrator, owner_message, wait_for


def _active(handler):
    task_id = handler.context.active_task_id()
    return handler.tasks.get(handler.namespace, task_id) if task_id else None


def test_telegram_task_binds_active_workspace_and_realtime(handler_factory) -> None:
    fake = FakeOrchestrator(["Готово"])
    handler = handler_factory(fake)
    response = handler.handle_update(owner_message(1, "/newtask workspace_id=WS-FOREIGN test"))
    assert response is not None
    wait_for(lambda: _active(handler) is not None)
    task = _active(handler)
    assert task["workspace_id"].startswith("WS-")
    assert task["workspace_id"] != "WS-FOREIGN"
    assert task["organization_id"].startswith("ORG-")
    assert isinstance(task["creator_id"], int)

    events = RealtimeService(handler.database).read(task["workspace_id"])
    assert any(event["task_id"] == task["task_id"] and event["type"] == "TASK_CREATED" for event in events)
    assert RealtimeService(handler.database).read("WS-FOREIGN") == []


def test_telegram_without_accessible_workspace_fails_closed(handler_factory) -> None:
    fake = FakeOrchestrator()
    handler = handler_factory(fake)
    workspace = handler.teams.list_workspaces(handler.namespace)[0]
    user_id = handler.database.user_id(handler.namespace)
    handler.database.set_workspace_member(workspace["id"], user_id, status="REMOVED")
    response = handler.handle_update(owner_message(1, "/newtask should not start"))
    assert response is not None and "NX_WORKSPACE_REQUIRED" in response.text
    assert handler.context.active_task_id() is None
    assert fake.calls == []


def test_continuation_cannot_cross_workspace(handler_factory) -> None:
    fake = FakeOrchestrator(["Готово"])
    handler = handler_factory(fake)
    handler.handle_update(owner_message(1, "/newtask original workspace"))
    wait_for(lambda: _active(handler) is not None)
    wait_for(lambda: fake.started.is_set())
    original = _active(handler)
    organization_id = original["organization_id"]
    second = handler.teams.create_workspace(handler.namespace, organization_id, "Second Workspace")
    session = handler.context.load()
    session = handler.context.bind_workspace(
        session,
        owner_namespace=handler.namespace,
        organization_id=organization_id,
        workspace_id=second["id"],
    )
    handler.context.save(session)
    calls = len(fake.calls)
    response = handler.handle_update(owner_message(2, "continue in foreign scope"))
    assert response is not None and "NX_PERMISSION_DENIED" in response.text
    assert len(fake.calls) == calls
    assert handler.tasks.get(handler.namespace, original["task_id"])["workspace_id"] != second["id"]


def test_status_audit_is_safe_and_does_not_call_llm(handler_factory) -> None:
    fake = FakeOrchestrator()
    handler = handler_factory(fake)
    before = len(fake.calls)
    response = handler.handle_update(owner_message(1, "/status"))
    assert response is not None
    assert len(fake.calls) == before
    records = [json.loads(line) for line in handler.audit.repository.path.read_text(encoding="utf-8").splitlines()]
    status = [record for record in records if record["event"] == "TELEGRAM_STATUS_VIEWED"][-1]
    serialized = json.dumps(status, ensure_ascii=False)
    assert status["metadata"]["command_type"] == "status"
    assert "telegram_id" not in serialized.casefold()
    assert "bot_token" not in serialized.casefold()
    assert "raw_context" not in serialized.casefold()


def test_realtime_cursor_deduplicates_and_preserves_scope(handler_factory) -> None:
    handler = handler_factory(FakeOrchestrator(["Готово"]))
    handler.handle_update(owner_message(1, "/newtask cursor test"))
    wait_for(lambda: _active(handler) is not None)
    task = _active(handler)
    service = RealtimeService(handler.database)
    first = service.read(task["workspace_id"])
    assert first
    after = service.read(task["workspace_id"], after_event_id=first[-1]["event_id"])
    assert all(event["event_id"] not in {item["event_id"] for item in first} for event in after)
