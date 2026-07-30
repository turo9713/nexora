from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from nexora.database import SQLiteRepository
from nexora.integrations.telegram_runtime.services.approval_service import ApprovalService
from nexora.integrations.telegram_runtime.services.audit_service import AuditService
from nexora.integrations.telegram_runtime.services.cancellation_service import CancellationService
from nexora.integrations.telegram_runtime.services.execution_service import ExecutionService
from nexora.integrations.telegram_runtime.services.idempotency_service import IdempotencyService
from nexora.integrations.telegram_runtime.services.task_service import TaskService
from nexora.integrations.telegram_runtime.storage.action_repository import ActionRepository
from nexora.integrations.telegram_runtime.storage.approval_repository import ApprovalRepository
from nexora.integrations.telegram_runtime.storage.audit_repository import AuditRepository
from nexora.integrations.telegram_runtime.storage.context_repository import ContextRepository
from nexora.integrations.telegram_runtime.storage.task_repository import TaskRepository


OWNER = "a" * 32
PROJECT = Path(__file__).resolve().parents[1]


def platform(tmp_path: Path):
    database = SQLiteRepository(tmp_path / "database" / "nexora.sqlite3")
    assert database.migrate() == 14
    tasks = TaskService(TaskRepository(tmp_path / "tasks"), database=database)
    context = ContextRepository(tmp_path / "context")
    approvals = ApprovalService(ApprovalRepository(tmp_path / "approvals"), database=database)
    idempotency = IdempotencyService(ActionRepository(tmp_path / "actions"))
    audit = AuditService(AuditRepository(tmp_path / "audit"), database=database)
    cancellations = CancellationService(tasks, approvals, context, idempotency)
    return database, tasks, context, idempotency, audit, cancellations


def create_task(tasks: TaskService, context: ContextRepository, title: str = "Queue test"):
    session = context.new()
    task = tasks.create(OWNER, title, str(session["session_id"]))
    session = context.set_active_task(session, task["task_id"])
    session = context.add_turn(session, "user", title)
    context.save(session)
    return task, session


def test_migration_014_is_reversible_and_backed_up(tmp_path: Path) -> None:
    database = SQLiteRepository(tmp_path / "database" / "nexora.sqlite3")
    assert database.migrate() == 14
    assert database.path.with_suffix(database.path.suffix + ".pre-v14.backup").is_file()
    with sqlite3.connect(database.path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"execution_jobs", "execution_job_events"} <= tables
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    database.rollback(14)
    assert database.schema_version() == 13


def test_priority_claim_idempotency_and_no_double_run(tmp_path: Path) -> None:
    database, tasks, context, _, _, _ = platform(tmp_path)
    first, first_session = create_task(tasks, context, "Normal priority")
    second = tasks.create(OWNER, "High priority", "session-high")
    normal = database.enqueue_execution_job(
        owner=OWNER,
        task_id=first["task_id"],
        session_id=str(first_session["session_id"]),
        worker_group="test",
        idempotency_key="normal",
        priority=3,
    )
    duplicate = database.enqueue_execution_job(
        owner=OWNER,
        task_id=first["task_id"],
        session_id=str(first_session["session_id"]),
        worker_group="test",
        idempotency_key="normal",
        priority=9,
    )
    assert duplicate["id"] == normal["id"]
    high = database.enqueue_execution_job(
        owner=OWNER,
        task_id=second["task_id"],
        session_id="session-high",
        worker_group="test",
        idempotency_key="high",
        priority=9,
    )
    first_claim = database.claim_execution_job(
        worker_group="test",
        owner=OWNER,
        worker_id="priority-worker",
    )
    assert first_claim and first_claim["id"] == high["id"]
    claimed: list[str] = []
    lock = threading.Lock()

    def claim(worker: int) -> None:
        item = database.claim_execution_job(
            worker_group="test",
            owner=OWNER,
            worker_id=f"worker-{worker}",
        )
        if item is not None:
            with lock:
                claimed.append(str(item["id"]))

    threads = [threading.Thread(target=claim, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert claimed == [normal["id"]]


class RetryOrchestrator:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    def run_task(self, task, workflow_name):
        self.calls += 1
        if self.calls == 1 and self.error is not None:
            raise self.error
        return {"result": {"summary": "QUEUE_WORKER_OK"}}


def wait_for_status(tasks: TaskService, task_id: str, expected: set[str], timeout: float = 8) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = tasks.get(OWNER, task_id)
        if task and task["status"] in expected:
            return task
        time.sleep(0.05)
    raise AssertionError(f"task did not reach {expected}")


def wait_for_job(database: SQLiteRepository, expected: set[str], timeout: float = 8) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        jobs = database.list_execution_jobs(OWNER)
        if jobs and jobs[0]["status"] in expected:
            return jobs[0]
        time.sleep(0.05)
    raise AssertionError(f"job did not reach {expected}")


def service(tmp_path: Path, orchestrator):
    database, tasks, context, idempotency, audit, cancellations = platform(tmp_path)
    execution = ExecutionService(
        orchestrator,
        tasks,
        context,
        cancellations,
        idempotency,
        audit,
        "task_flow",
        lambda _text, _markup=None: None,
        owner_namespace=OWNER,
        worker_group="test",
        max_workers=2,
        max_attempts=2,
    )
    return database, tasks, context, cancellations, execution


def test_transient_failure_retries_once_and_succeeds(tmp_path: Path) -> None:
    orchestrator = RetryOrchestrator(TimeoutError("provider timed out"))
    database, tasks, context, _, execution = service(tmp_path, orchestrator)
    task, session = create_task(tasks, context)
    try:
        assert execution.submit(OWNER, task["task_id"], str(session["session_id"]))
        result = wait_for_status(tasks, task["task_id"], {"COMPLETED"})
        assert result["result_summary"] == "QUEUE_WORKER_OK"
        job = wait_for_job(database, {"SUCCEEDED"})
        assert job["attempt"] == 2
        assert orchestrator.calls == 2
    finally:
        execution.shutdown()


def test_validation_failure_is_not_retried(tmp_path: Path) -> None:
    orchestrator = RetryOrchestrator(ValueError("schema validation failed"))
    database, tasks, context, _, execution = service(tmp_path, orchestrator)
    task, session = create_task(tasks, context)
    try:
        assert execution.submit(OWNER, task["task_id"], str(session["session_id"]))
        result = wait_for_status(tasks, task["task_id"], {"FAILED"})
        assert result["error_code"] == "NX_VALIDATION_ERROR"
        job = wait_for_job(database, {"FAILED"})
        assert job["attempt"] == 1
        assert orchestrator.calls == 1
    finally:
        execution.shutdown()


def test_cancel_invalidates_queued_job_and_recovery_is_bounded(tmp_path: Path) -> None:
    database, tasks, context, _, _, cancellations = platform(tmp_path)
    task, session = create_task(tasks, context)
    job = database.enqueue_execution_job(
        owner=OWNER,
        task_id=task["task_id"],
        session_id=str(session["session_id"]),
        worker_group="test",
        idempotency_key="cancel-me",
        max_attempts=1,
    )
    cancelled, _ = cancellations.cancel(OWNER, task["task_id"])
    assert cancelled is True
    assert database.list_execution_jobs(OWNER)[0]["status"] == "CANCELLED"

    recovery_task = tasks.create(OWNER, "Recovery", "recovery-session")
    recovery = database.enqueue_execution_job(
        owner=OWNER,
        task_id=recovery_task["task_id"],
        session_id="recovery-session",
        worker_group="recovery",
        idempotency_key="recovery",
        max_attempts=1,
    )
    assert database.claim_execution_job(
        worker_group="recovery",
        owner=OWNER,
        worker_id="dead-worker",
    )
    with sqlite3.connect(database.path) as connection:
        connection.execute(
            "UPDATE execution_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
            (recovery["id"],),
        )
    failed = database.recover_execution_jobs("recovery", OWNER)
    assert [item["id"] for item in failed] == [recovery["id"]]
    assert database.list_execution_jobs(OWNER, status="FAILED")[0]["id"] == recovery["id"]


def test_queue_dashboard_is_read_only() -> None:
    script = (PROJECT / "dashboard" / "frontend" / "app.js").read_text(encoding="utf-8")
    server = (PROJECT / "dashboard" / "backend" / "server.py").read_text(encoding="utf-8")
    assert 'api("/api/queue")' in script
    assert 'navigate(`/tasks/${encodeURIComponent(item.task_id)}`)' in script
    assert 'path == "/api/queue"' in server
    assert 'api("/api/queue",{method:"POST"' not in script
    assert '"/api/queue"' not in server.split("def do_POST", 1)[-1].split("def ", 1)[0]
