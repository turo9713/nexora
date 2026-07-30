from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from .conftest import (
    FakeOrchestrator,
    OWNER_ID,
    callback_update,
    owner_message,
    wait_for,
)


def active_task(handler):
    task_id = handler.context.active_task_id()
    return handler.tasks.get(handler.namespace, task_id) if task_id else None


def test_allowed_owner_status_without_task_does_not_call_llm(handler_factory):
    fake = FakeOrchestrator()
    handler = handler_factory(fake)
    response = handler.handle_update(owner_message(1, "/status"))
    assert "нет активной задачи" in response.text.casefold()
    assert fake.calls == []


def test_unknown_user_gets_access_denied_and_cannot_change_context(handler_factory):
    fake = FakeOrchestrator()
    handler = handler_factory(fake)
    response = handler.handle_update(owner_message(1, "/newtask Hidden", owner_id=999))
    assert response.text == "ACCESS_DENIED"
    assert handler.context.load() is None
    assert fake.calls == []


def test_completed_task_sends_private_document_artifact(handler_factory):
    delivered = []
    handler = handler_factory(
        FakeOrchestrator(["Безопасный итог"]),
        artifact_notifier=lambda name, media_type, payload, caption: delivered.append(
            (name, media_type, payload, caption)
        ),
    )
    handler.handle_update(owner_message(1, "/newtask Artifact result"))
    wait_for(lambda: active_task(handler)["status"] == "COMPLETED" and bool(delivered))

    name, media_type, payload, caption = delivered[0]
    assert name.endswith("-result.docx")
    assert media_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert payload.startswith(b"PK")
    assert "полный структурированный отчёт" in caption
    workspace_id = active_task(handler)["workspace_id"]
    files = list((handler.artifacts.repository.root / handler.namespace / workspace_id).rglob("*"))
    assert files


def test_explicit_formats_are_all_delivered_and_required_before_completion(handler_factory):
    delivered = []
    fake = FakeOrchestrator(
        ["Report ready. The spreadsheet and archive contain safe results."]
    )
    handler = handler_factory(
        fake,
        artifact_notifier=lambda name, media_type, payload, caption: delivered.append(
            (name, media_type, payload, caption)
        ),
    )
    handler.handle_update(
        owner_message(1, "/newtask Create a report, Excel spreadsheet and ZIP archive")
    )
    wait_for(lambda: active_task(handler)["status"] == "COMPLETED")
    wait_for(lambda: len(delivered) == 4)

    suffixes = [Path(name).suffix for name, _, _, _ in delivered]
    assert suffixes == [".docx", ".xlsx", ".pdf", ".zip"]
    assert all(payload for _, _, payload, _ in delivered)
    assert all("Задача:" in caption for _, _, _, caption in delivered)
    assert "artifact layer" in fake.calls[0]["description"]


def test_missing_required_artifact_fails_closed(handler_factory, monkeypatch):
    handler = handler_factory(FakeOrchestrator(["Safe result"]))

    def fail_create(*args, **kwargs):
        raise OSError("simulated artifact storage failure")

    monkeypatch.setattr(handler.artifacts.repository, "create", fail_create)
    handler.handle_update(owner_message(1, "/newtask Create Excel report"))
    wait_for(lambda: active_task(handler)["status"] == "FAILED")
    assert active_task(handler)["status"] != "COMPLETED"


def test_unknown_user_cannot_read_history(handler_factory):
    handler = handler_factory(FakeOrchestrator())
    response = handler.handle_update(owner_message(1, "/history", owner_id=999))
    assert response.text == "ACCESS_DENIED"
    assert "История" not in response.text


def test_newtask_reaches_clarifying_and_status_is_local(handler_factory):
    fake = FakeOrchestrator(["Уточните, какую платформу использовать?"])
    notifications = []
    handler = handler_factory(fake, lambda text, markup=None: notifications.append(text))
    handler.handle_update(owner_message(1, "/newtask Build an app"))
    wait_for(lambda: active_task(handler)["status"] == "CLARIFYING" and bool(notifications))
    calls_before = len(fake.calls)
    response = handler.handle_update(owner_message(2, "/status"))
    assert "CLARIFYING" in response.text and "10%" in response.text
    assert len(fake.calls) == calls_before
    assert notifications


def test_status_reports_in_progress_without_llm_call(handler_factory):
    fake = FakeOrchestrator(block=True)
    handler = handler_factory(fake)
    handler.handle_update(owner_message(1, "/newtask Long task"))
    wait_for(lambda: fake.started.is_set())
    wait_for(lambda: active_task(handler)["status"] == "IN_PROGRESS")
    response = handler.handle_update(owner_message(2, "/status"))
    assert "IN_PROGRESS" in response.text
    assert len(fake.calls) == 1
    fake.release.set()


def test_status_reports_waiting_approval(handler_factory):
    fake = FakeOrchestrator()
    handler = handler_factory(fake)
    handler.handle_update(owner_message(1, "/newtask Перезапусти сервис"))
    response = handler.handle_update(owner_message(2, "/status"))
    assert "WAITING_APPROVAL" in response.text
    assert fake.calls == []


def test_plain_text_continues_dialogue_and_completes(handler_factory):
    fake = FakeOrchestrator(["Уточните платформу?", "Готовый результат"])
    handler = handler_factory(fake)
    handler.handle_update(owner_message(1, "/newtask Remember context"))
    wait_for(lambda: active_task(handler)["status"] == "CLARIFYING")
    task_id = handler.context.active_task_id()
    handler.handle_update(owner_message(2, "Telegram"))
    wait_for(lambda: active_task(handler)["status"] == "COMPLETED")
    task = active_task(handler)
    assert task["task_id"] == task_id
    assert task["progress"] == 100
    assert "OWNER: Remember context" in fake.calls[1]["description"]
    assert "ASSISTANT: Уточните платформу?" in fake.calls[1]["description"]
    assert "OWNER: Telegram" in fake.calls[1]["description"]


def test_history_and_task_details_show_only_safe_owner_data(handler_factory):
    fake = FakeOrchestrator(["Готовый результат"])
    handler = handler_factory(fake)
    handler.handle_update(owner_message(1, "/newtask Safe title"))
    wait_for(lambda: active_task(handler)["status"] == "COMPLETED")
    task_id = handler.context.active_task_id()
    history = handler.handle_update(owner_message(2, "/history 10"))
    details = handler.handle_update(owner_message(3, f"/task {task_id}"))
    assert task_id in history.text
    assert "Готовый результат" in details.text
    assert str(OWNER_ID) not in history.text + details.text


def test_history_rejects_limit_over_twenty(handler_factory):
    handler = handler_factory(FakeOrchestrator())
    response = handler.handle_update(owner_message(1, "/history 100"))
    assert "от 1 до 20" in response.text


def test_task_details_do_not_disclose_foreign_task(handler_factory):
    handler = handler_factory(FakeOrchestrator())
    foreign_namespace = "f" * 32
    foreign = handler.tasks.create(foreign_namespace, "Foreign secret", "session")
    response = handler.handle_update(owner_message(1, f"/task {foreign['task_id']}"))
    assert response.text == "Задача не найдена или недоступна."
    assert "Foreign secret" not in response.text


def test_cancel_stops_inflight_workflow_and_plain_text_does_not_continue(handler_factory):
    fake = FakeOrchestrator(block=True)
    notifications = []
    handler = handler_factory(fake, lambda text, markup=None: notifications.append(text))
    handler.handle_update(owner_message(1, "/newtask Long task"))
    wait_for(lambda: fake.started.is_set())
    task_id = handler.context.active_task_id()
    cancelled = handler.handle_update(owner_message(2, "/cancel"))
    assert "отменена" in cancelled.text
    assert handler.tasks.get(handler.namespace, task_id)["status"] == "CANCELLED"
    assert handler.context.load() is None
    followup = handler.handle_update(owner_message(3, "Continue old task"))
    assert "/newtask" in followup.text
    assert len(fake.calls) == 1
    fake.release.set()
    wait_for(lambda: handler.tasks.get(handler.namespace, task_id)["status"] == "CANCELLED")


def test_repeated_cancel_is_safe(handler_factory):
    fake = FakeOrchestrator(block=True)
    handler = handler_factory(fake)
    handler.handle_update(owner_message(1, "/newtask Long task"))
    wait_for(lambda: fake.started.is_set())
    handler.handle_update(owner_message(2, "/cancel"))
    repeated = handler.handle_update(owner_message(3, "/cancel"))
    assert "Нет активной задачи" in repeated.text
    fake.release.set()


def test_approval_confirm_executes_once(handler_factory):
    fake = FakeOrchestrator(["Approved plan"])
    handler = handler_factory(fake)
    request = handler.handle_update(owner_message(1, "/newtask Перезапусти сервис"))
    callback_data = request.reply_markup["inline_keyboard"][0][0]["callback_data"]
    first = handler.handle_update(callback_update(2, callback_data, callback_id="approve-1"))
    wait_for(lambda: active_task(handler)["status"] == "COMPLETED")
    second = handler.handle_update(callback_update(3, callback_data, callback_id="approve-2"))
    assert "подтверждено" in first.text.casefold()
    assert "уже использовано" in second.text.casefold()
    assert len(fake.calls) == 1


def test_approval_rejects_without_execution(handler_factory):
    fake = FakeOrchestrator()
    handler = handler_factory(fake)
    request = handler.handle_update(owner_message(1, "/newtask Перезапусти сервис"))
    callback_data = request.reply_markup["inline_keyboard"][0][1]["callback_data"]
    response = handler.handle_update(callback_update(2, callback_data))
    assert "отклонено" in response.text.casefold()
    assert fake.calls == []


def test_dashboard_approval_reconciliation_resumes_once(handler_factory):
    fake = FakeOrchestrator(["Approved through dashboard"])
    handler = handler_factory(fake)
    request = handler.handle_update(owner_message(1, "/newtask Перезапусти сервис"))
    callback_data = request.reply_markup["inline_keyboard"][0][0]["callback_data"]
    approval_id = callback_data.rsplit(":", 1)[-1]
    approval = handler.approvals.repository.get(handler.namespace, approval_id)
    status, _ = handler.approvals.decide(
        handler.namespace,
        approval_id,
        approval["session_id"],
        "approve",
    )
    assert status == "APPROVED"
    assert handler.reconcile_external_approval() is True
    assert handler.reconcile_external_approval() is False
    wait_for(lambda: active_task(handler)["status"] == "COMPLETED")
    assert len(fake.calls) == 1


def test_expired_approval_does_not_execute(handler_factory):
    fake = FakeOrchestrator()
    handler = handler_factory(fake)
    request = handler.handle_update(owner_message(1, "/newtask Перезапусти сервис"))
    callback_data = request.reply_markup["inline_keyboard"][0][0]["callback_data"]
    approval_id = callback_data.rsplit(":", 1)[-1]
    approval = handler.approvals.repository.get(handler.namespace, approval_id)
    approval["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    handler.approvals.repository.save(handler.namespace, approval)
    response = handler.handle_update(callback_update(2, callback_data))
    assert "истекло" in response.text.casefold()
    assert handler.tasks.history(handler.namespace, 1)[0]["status"] == "EXPIRED"
    assert fake.calls == []


def test_unknown_callback_cannot_approve(handler_factory):
    fake = FakeOrchestrator()
    handler = handler_factory(fake)
    request = handler.handle_update(owner_message(1, "/newtask Перезапусти сервис"))
    callback_data = request.reply_markup["inline_keyboard"][0][0]["callback_data"]
    response = handler.handle_update(callback_update(2, callback_data, owner_id=999))
    assert response.callback_answer == "ACCESS_DENIED"
    assert fake.calls == []


def test_cancel_invalidates_pending_approval(handler_factory):
    handler = handler_factory(FakeOrchestrator())
    request = handler.handle_update(owner_message(1, "/newtask Перезапусти сервис"))
    approval_id = request.reply_markup["inline_keyboard"][0][0]["callback_data"].rsplit(":", 1)[-1]
    handler.handle_update(owner_message(2, "/cancel"))
    saved = handler.approvals.repository.get(handler.namespace, approval_id)
    assert saved["status"] == "INVALIDATED"


def test_duplicate_telegram_update_does_not_create_second_task(handler_factory):
    fake = FakeOrchestrator(["Done"])
    handler = handler_factory(fake)
    update = owner_message(77, "/newtask Idempotent task")
    first = handler.handle_update(update)
    second = handler.handle_update(update)
    assert first is not None and second is None
    wait_for(lambda: len(fake.calls) == 1)
    assert len(handler.tasks.history(handler.namespace, 20)) == 1
    assert len(fake.calls) == 1


def test_failed_provider_returns_safe_error_and_audit_is_redacted(handler_factory):
    fake = FakeOrchestrator(error=RuntimeError("provider failed Authorization: Bearer secret-value"))
    notifications = []
    handler = handler_factory(fake, lambda text, markup=None: notifications.append(text))
    handler.handle_update(owner_message(1, "/newtask Failing task"))
    wait_for(lambda: active_task(handler)["status"] == "FAILED")
    wait_for(lambda: bool(notifications))
    assert "NX_PROVIDER_ERROR" in notifications[-1]
    audit = handler.audit.repository.path.read_text(encoding="utf-8")
    assert "secret-value" not in audit and "Traceback" not in audit


def test_notification_failure_does_not_change_completed_task(handler_factory):
    fake = FakeOrchestrator(["Done"])

    def broken_notifier(text, markup=None):
        raise RuntimeError("Telegram API unavailable")

    handler = handler_factory(fake, broken_notifier)
    handler.handle_update(owner_message(1, "/newtask Notification failure"))
    wait_for(lambda: active_task(handler)["status"] == "COMPLETED")
    assert active_task(handler)["error_code"] is None


def test_state_recovers_after_handler_restart(handler_factory):
    first = handler_factory(FakeOrchestrator(["Done"]), suffix="restart")
    first.handle_update(owner_message(1, "/newtask Persisted task"))
    wait_for(lambda: active_task(first)["status"] == "COMPLETED")
    task_id = first.context.active_task_id()
    first.close()
    second = handler_factory(FakeOrchestrator(), suffix="restart")
    response = second.handle_update(owner_message(2, "/status"))
    assert task_id in response.text and "COMPLETED" in response.text


def test_menu_and_help_are_russian_and_complete(handler_factory):
    handler = handler_factory(FakeOrchestrator())
    menu = handler.handle_update(owner_message(1, "/menu"))
    help_response = handler.handle_update(owner_message(2, "/help"))
    assert "Главное меню" in menu.text
    for command in ("/newtask", "/status", "/history", "/task", "/cancel", "/reset", "/menu", "/help"):
        assert command in help_response.text
