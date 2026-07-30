from __future__ import annotations

import threading
import time
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
CompletionCallback = Callable[[str, str], None]
CompletionPreflight = Callable[[str], Any]


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
        completion_callback: CompletionCallback | None = None,
        completion_preflight: CompletionPreflight | None = None,
        source: str = "telegram_runtime_v1.4",
        created_by: str = "telegram-owner",
        owner_namespace: str | None = None,
        worker_group: str = "runtime",
        max_workers: int = 2,
        max_attempts: int = 2,
        lease_seconds: int = 300,
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
        self.completion_callback = completion_callback
        self.completion_preflight = completion_preflight
        self.source = source
        self.created_by = created_by
        self.owner_namespace = owner_namespace
        self.worker_group = worker_group
        self.max_workers = max(1, min(8, int(max_workers)))
        self.max_attempts = max(1, min(5, int(max_attempts)))
        self.lease_seconds = max(30, int(lease_seconds))
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nexora-task")
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._workers: list[threading.Thread] = []
        self._queue_enabled = bool(
            getattr(self.tasks, "database", None) is not None
            and self.tasks.database.schema_version() >= 14
        )
        if self._queue_enabled and self.owner_namespace:
            self._start_workers(self.owner_namespace)

    def submit(self, namespace: str, task_id: str, session_id: str, *, priority: int = 5) -> bool:
        task = self.tasks.get(namespace, task_id)
        if task is None:
            return False
        turn_number = int(task.get("turn_number", 0)) + 1
        key = f"workflow:{task_id}:turn:{turn_number}"
        if not self.idempotency.begin(namespace, key, "workflow", task_id=task_id):
            return False
        task = self.tasks.update_fields(namespace, task_id, turn_number=turn_number)
        self.tasks.transition(namespace, task_id, "QUEUED", event="WORKFLOW_QUEUED")
        if self._queue_enabled:
            try:
                self._start_workers(namespace)
                job = self.tasks.database.enqueue_execution_job(
                    owner=namespace,
                    task_id=task_id,
                    session_id=session_id,
                    worker_group=self.worker_group,
                    idempotency_key=key,
                    priority=priority,
                    max_attempts=self.max_attempts,
                )
            except Exception as exc:
                self.tasks.update_fields(namespace, task_id, error_code="NX_INTERNAL_ERROR")
                self.tasks.transition(namespace, task_id, "FAILED", event="WORKFLOW_QUEUE_FAILED")
                self.idempotency.set_status(namespace, key, "FAILED")
                self.audit.record(
                    "WORKFLOW_QUEUE_FAILED",
                    task_id=task_id,
                    error_type=type(exc).__name__,
                    error=redact_text(exc),
                )
                raise RuntimeError("execution queue unavailable") from exc
            self.audit.record(
                "WORKFLOW_JOB_QUEUED",
                task_id=task_id,
                job_id=job["id"],
                worker_group=self.worker_group,
                priority=int(job["priority"]),
            )
            self._wake.set()
        else:
            self._executor.submit(self._run, namespace, task_id, session_id, turn_number, key)
        return True

    def _start_workers(self, namespace: str) -> None:
        with self._lock:
            if self._workers:
                if self.owner_namespace != namespace:
                    raise RuntimeError("execution queue owner mismatch")
                return
            self.owner_namespace = namespace
            failed = self.tasks.database.recover_execution_jobs(self.worker_group, namespace)
            for job in failed:
                self._fail_recovered_job(namespace, job)
            for index in range(self.max_workers):
                worker = threading.Thread(
                    target=self._worker_loop,
                    args=(
                        namespace,
                        f"{self.worker_group}-{index + 1}-{uuid4().hex[:8]}",
                        index == 0,
                    ),
                    name=f"nexora-{self.worker_group}-{index + 1}",
                    daemon=True,
                )
                self._workers.append(worker)
                worker.start()

    def _fail_recovered_job(self, namespace: str, job: dict[str, Any]) -> None:
        task_id = str(job["task_id"])
        key = str(job["idempotency_key"])
        try:
            if not self.cancellations.is_cancelled(namespace, task_id):
                self.tasks.update_fields(namespace, task_id, error_code="NX_TIMEOUT")
                self.tasks.transition(namespace, task_id, "FAILED", event="WORKFLOW_RECOVERY_FAILED")
            self.idempotency.set_status(namespace, key, "FAILED")
            self.audit.record("WORKFLOW_RECOVERY_FAILED", task_id=task_id, code="NX_TIMEOUT")
        except (KeyError, OSError, RuntimeError) as exc:
            self.audit.record(
                "WORKFLOW_RECOVERY_STATE_FAILED",
                task_id=task_id,
                error_type=type(exc).__name__,
                error=redact_text(exc),
            )

    def _worker_loop(self, namespace: str, worker_id: str, recovery_leader: bool) -> None:
        next_recovery = time.monotonic() + 5
        while not self._stop.is_set():
            try:
                if recovery_leader and time.monotonic() >= next_recovery:
                    failed = self.tasks.database.recover_execution_jobs(self.worker_group, namespace)
                    for item in failed:
                        self._fail_recovered_job(namespace, item)
                    next_recovery = time.monotonic() + 5
                job = self.tasks.database.claim_execution_job(
                    worker_group=self.worker_group,
                    owner=namespace,
                    worker_id=worker_id,
                    lease_seconds=self.lease_seconds,
                )
                if job is None:
                    self._wake.wait(0.5)
                    self._wake.clear()
                    continue
                self._run(
                    namespace,
                    str(job["task_id"]),
                    str(job["session_id"]),
                    self._turn_number(str(job["idempotency_key"])),
                    str(job["idempotency_key"]),
                    job=job,
                    worker_id=worker_id,
                )
            except Exception as exc:
                self.audit.record(
                    "WORKER_LOOP_ERROR",
                    worker_group=self.worker_group,
                    error_type=type(exc).__name__,
                    error=redact_text(exc),
                )
                self._stop.wait(0.5)

    @staticmethod
    def _turn_number(key: str) -> int:
        try:
            return int(key.rsplit(":", 1)[-1])
        except (TypeError, ValueError):
            return 1

    def _run(
        self,
        namespace: str,
        task_id: str,
        session_id: str,
        turn_number: int,
        key: str,
        *,
        job: dict[str, Any] | None = None,
        worker_id: str | None = None,
    ) -> None:
        heartbeat_stop: threading.Event | None = None
        heartbeat: threading.Thread | None = None
        if job is not None and worker_id is not None:
            heartbeat_stop = threading.Event()
            heartbeat = threading.Thread(
                target=self._heartbeat_loop,
                args=(str(job["id"]), worker_id, heartbeat_stop),
                name=f"nexora-lease-{str(job['id'])[-8:]}",
                daemon=True,
            )
            heartbeat.start()
        try:
            if self.cancellations.is_cancelled(namespace, task_id):
                self.idempotency.set_status(namespace, key, "CANCELLED")
                self._finish_job(job, worker_id, "CANCELLED")
                return
            attempt = int(job.get("attempt", 1)) if job else 1
            if attempt > 1:
                current = self.tasks.get(namespace, task_id) or {}
                self.tasks.transition(
                    namespace,
                    task_id,
                    "IN_PROGRESS",
                    stage=f"Повтор безопасного запроса ({attempt}/{int(job['max_attempts'])})",
                    progress=int(current.get("progress", 40)),
                    event="WORKER_RETRY_STARTED",
                )
            else:
                self.tasks.transition(namespace, task_id, "PLANNING", event="WORKER_STARTED")
            if self.cancellations.is_cancelled(namespace, task_id):
                self.idempotency.set_status(namespace, key, "CANCELLED")
                self._finish_job(job, worker_id, "CANCELLED")
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
                self._finish_job(job, worker_id, "CANCELLED")
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
                if self.completion_preflight is not None:
                    self.completion_preflight(task_id)
                task = self.tasks.transition(namespace, task_id, "COMPLETED", event="WORKFLOW_COMPLETED")
            self._notify(format_task_outcome_v14(task), None)
            if task["status"] == "COMPLETED" and self.completion_callback is not None:
                try:
                    self.completion_callback(namespace, task_id)
                except Exception as exc:
                    self.audit.record(
                        "ARTIFACT_NOTIFICATION_FAILED",
                        task_id=task_id,
                        error_type=type(exc).__name__,
                        error=redact_text(exc),
                    )
            self.idempotency.set_status(namespace, key, "SUCCEEDED")
            self._finish_job(job, worker_id, "SUCCEEDED")
            self.audit.record("WORKFLOW_COMPLETED", task_id=task_id, status=task["status"])
        except Exception as exc:
            code = safe_error_code(exc)
            if self._retryable(job, code):
                current = self.tasks.get(namespace, task_id) or {}
                self.tasks.update_fields(namespace, task_id, error_code=code)
                self.tasks.transition(
                    namespace,
                    task_id,
                    "IN_PROGRESS",
                    stage="Временная ошибка — безопасный повтор запланирован",
                    progress=int(current.get("progress", 40)),
                    event="WORKFLOW_RETRY_SCHEDULED",
                )
                delay = min(30, 2 ** int(job["attempt"]))
                self._finish_job(job, worker_id, "RETRY_WAIT", error_code=code, retry_delay_seconds=delay)
                self.audit.record(
                    "WORKFLOW_RETRY_SCHEDULED",
                    task_id=task_id,
                    attempt=int(job["attempt"]),
                    max_attempts=int(job["max_attempts"]),
                    delay_seconds=delay,
                    code=code,
                )
                self._wake.set()
                return
            try:
                if not self.cancellations.is_cancelled(namespace, task_id):
                    self.tasks.update_fields(namespace, task_id, error_code=code)
                    self.tasks.transition(namespace, task_id, "FAILED", event="WORKFLOW_FAILED")
                self.idempotency.set_status(namespace, key, "FAILED")
                self._finish_job(job, worker_id, "FAILED", error_code=code)
            finally:
                self.audit.record(
                    "WORKFLOW_FAILED",
                    task_id=task_id,
                    error_type=type(exc).__name__,
                    error=redact_text(exc),
                    code=code,
                )
            self._notify(format_safe_error(code, task_id), None)
        finally:
            if heartbeat_stop is not None:
                heartbeat_stop.set()
            if heartbeat is not None:
                heartbeat.join(timeout=1)

    def _heartbeat_loop(self, job_id: str, worker_id: str, stop: threading.Event) -> None:
        interval = max(10, self.lease_seconds // 3)
        while not stop.wait(interval):
            try:
                if not self.tasks.database.renew_execution_job_lease(
                    job_id,
                    worker_id,
                    lease_seconds=self.lease_seconds,
                ):
                    return
            except Exception as exc:
                self.audit.record(
                    "WORKER_LEASE_RENEWAL_FAILED",
                    worker_group=self.worker_group,
                    error_type=type(exc).__name__,
                    error=redact_text(exc),
                )
                return

    @staticmethod
    def _retryable(job: dict[str, Any] | None, code: str) -> bool:
        return bool(
            job
            and code in {"NX_TIMEOUT", "NX_PROVIDER_ERROR"}
            and int(job.get("attempt", 0)) < int(job.get("max_attempts", 1))
        )

    def _finish_job(
        self,
        job: dict[str, Any] | None,
        worker_id: str | None,
        status: str,
        *,
        error_code: str | None = None,
        retry_delay_seconds: int = 0,
    ) -> None:
        if job is None or worker_id is None:
            return
        if not self.tasks.database.finish_execution_job(
            str(job["id"]),
            worker_id,
            status,
            error_code=error_code,
            retry_delay_seconds=retry_delay_seconds,
        ):
            raise RuntimeError("execution job lease lost")

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
        self._stop.set()
        self._wake.set()
        for worker in self._workers:
            worker.join(timeout=2)
        self._executor.shutdown(wait=False, cancel_futures=True)
