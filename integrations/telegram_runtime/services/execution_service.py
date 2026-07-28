from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable
from uuid import uuid4

from ..formatter import extract_model_text, format_safe_error, format_task_outcome_v14
from ..security.redaction import redact_text, safe_error_code
from ..storage.context_repository import ContextRepository
from .audit_service import AuditService
from .cancellation_service import CancellationService
from .idempotency_service import IdempotencyService
from .task_service import TaskService


Notifier = Callable[[str, dict[str, Any] | None], None]


def response_requests_clarification(text: str) -> bool:
    lowered = text.casefold()
    markers = ("уточните", "ответьте", "какой", "какая", "какие", "which", "clarify", "please provide")
    return "?" in text and any(marker in lowered for marker in markers)


class ExecutionService:
    def __init__(
        self,
        orchestrator: Any,
        tasks: TaskService,
        context: ContextRepository,
        cancellations: CancellationService,
        idempotency: IdempotencyService,
        audit: AuditService,
        workflow_name: str,
        notifier: Notifier,
        event_bus: Any | None = None,
        execution_guard: Callable[[], bool] | None = None,
        source: str = "telegram_runtime_v1.4",
        created_by: str = "telegram-owner",
    ) -> None:
        self.orchestrator = orchestrator
        self.tasks = tasks
        self.context = context
        self.cancellations = cancellations
        self.idempotency = idempotency
        self.audit = audit
        self.workflow_name = workflow_name
        self.notifier = notifier
        self.event_bus = event_bus
        self.execution_guard = execution_guard
        self.source = source
        self.created_by = created_by
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nexora-task")
        self._lock = threading.Lock()

    def submit(self, namespace: str, task_id: str, session_id: str) -> bool:
        task = self.tasks.get(namespace, task_id)
        if task is None:
            return False
        turn_number = int(task.get("turn_number", 0)) + 1
        key = f"workflow:{task_id}:turn:{turn_number}"
        if not self.idempotency.begin(namespace, key, "workflow", task_id=task_id):
            return False
        task = self.tasks.update_fields(namespace, task_id, turn_number=turn_number)
        self.tasks.transition(namespace, task_id, "QUEUED", event="WORKFLOW_QUEUED")
        self._executor.submit(self._run, namespace, task_id, session_id, turn_number, key)
        return True

    def _run(self, namespace: str, task_id: str, session_id: str, turn_number: int, key: str) -> None:
        try:
            if self.cancellations.is_cancelled(namespace, task_id):
                self.idempotency.set_status(namespace, key, "CANCELLED")
                return
            self.tasks.transition(namespace, task_id, "PLANNING", event="WORKER_STARTED")
            if self.cancellations.is_cancelled(namespace, task_id):
                self.idempotency.set_status(namespace, key, "CANCELLED")
                return
            self.tasks.transition(namespace, task_id, "IN_PROGRESS", event="PROVIDER_REQUEST")

            if self.execution_guard is not None and not self.execution_guard():
                raise PermissionError("agent route denied by platform policy")
            if self.event_bus is not None:
                self.event_bus.publish(
                    "AGENT_STARTED",
                    task_id=task_id,
                    metadata={"agent": "orchestrator", "workflow": self.workflow_name},
                )

            session = self.context.load()
            if session is None or session.get("session_id") != session_id or session.get("active_task_id") != task_id:
                raise RuntimeError("dialogue context is unavailable")
            prompt = self.context.build_prompt(session)
            runtime_task_id = f"{task_id}-S{turn_number:03d}-{uuid4().hex[:4].upper()}"
            outcome = self.orchestrator.run_task(
                {
                    "id": runtime_task_id,
                    "title": str(self.tasks.get(namespace, task_id).get("title", task_id))[:100],
                    "description": prompt,
                    "created_by": self.created_by,
                    "workflow": self.workflow_name,
                    "parent_task_id": session.get("last_task_id"),
                    "context": {
                        "source": self.source,
                        "external_actions_allowed": False,
                        "public_task_id": task_id,
                        "dialogue_session_id": session_id,
                        "dialogue_turn_count": len(session.get("turns", [])),
                    },
                    "approval_required": False,
                },
                self.workflow_name,
            )
            if self.event_bus is not None:
                self.event_bus.publish(
                    "AGENT_FINISHED",
                    task_id=task_id,
                    metadata={"agent": "orchestrator", "workflow": self.workflow_name, "result": "SUCCESS"},
                )
            if self.cancellations.is_cancelled(namespace, task_id):
                self.idempotency.set_status(namespace, key, "CANCELLED")
                self.audit.record("WORKFLOW_RESULT_DISCARDED_AFTER_CANCEL", task_id=task_id)
                return

            result = outcome.get("result") if isinstance(outcome.get("result"), dict) else {}
            assistant_text = extract_model_text(result) or str(result.get("summary") or "Задача обработана")
            current_session = self.context.load()
            if current_session is None or current_session.get("session_id") != session_id:
                raise RuntimeError("dialogue context changed during execution")
            current_session = self.context.add_turn(current_session, "assistant", assistant_text)
            current_session = self.context.set_last_task(current_session, runtime_task_id)
            self.context.save(current_session)

            self.tasks.update_fields(
                namespace,
                task_id,
                result_summary=assistant_text,
                last_runtime_task_id=runtime_task_id,
                error_code=None,
                pending_approval_id=None,
            )
            if response_requests_clarification(assistant_text):
                task = self.tasks.transition(namespace, task_id, "CLARIFYING", event="CLARIFICATION_REQUESTED")
            else:
                task = self.tasks.transition(namespace, task_id, "COMPLETED", event="WORKFLOW_COMPLETED")
            self._notify(format_task_outcome_v14(task), None)
            self.idempotency.set_status(namespace, key, "SUCCEEDED")
            self.audit.record("WORKFLOW_COMPLETED", task_id=task_id, status=task["status"])
        except Exception as exc:
            code = safe_error_code(exc)
            try:
                if not self.cancellations.is_cancelled(namespace, task_id):
                    self.tasks.update_fields(namespace, task_id, error_code=code)
                    self.tasks.transition(namespace, task_id, "FAILED", event="WORKFLOW_FAILED")
                self.idempotency.set_status(namespace, key, "FAILED")
            finally:
                self.audit.record(
                    "WORKFLOW_FAILED",
                    task_id=task_id,
                    error_type=type(exc).__name__,
                    error=redact_text(exc),
                    code=code,
                )
            self._notify(format_safe_error(code, task_id), None)

    def _notify(self, text: str, markup: dict[str, Any] | None) -> None:
        try:
            self.notifier(text, markup)
        except Exception as exc:
            self.audit.record(
                "TELEGRAM_NOTIFICATION_FAILED",
                error_type=type(exc).__name__,
                error=redact_text(exc),
            )

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
