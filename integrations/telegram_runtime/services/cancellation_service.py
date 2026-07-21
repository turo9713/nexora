from __future__ import annotations

from ..storage.context_repository import ContextRepository
from .approval_service import ApprovalService
from .idempotency_service import IdempotencyService
from .task_service import TaskService


class CancellationService:
    def __init__(
        self,
        tasks: TaskService,
        approvals: ApprovalService,
        context: ContextRepository,
        idempotency: IdempotencyService | None = None,
    ) -> None:
        self.tasks = tasks
        self.approvals = approvals
        self.context = context
        self.idempotency = idempotency

    def cancel(self, namespace: str, task_id: str) -> tuple[bool, dict | None]:
        task = self.tasks.get(namespace, task_id)
        if task is None:
            return False, None
        if task.get("status") in {"CANCELLED", "FAILED", "EXPIRED"}:
            self.context.clear()
            return False, task
        if task.get("status") == "COMPLETED":
            self.context.clear()
            return False, task
        task = self.tasks.update_fields(namespace, task_id, cancellation_requested=True, pending_approval_id=None)
        task = self.tasks.transition(namespace, task_id, "CANCELLED", event="OWNER_CANCELLED")
        task_approvals = self.approvals.repository.list_for_task(namespace, task_id)
        self.approvals.invalidate_task(namespace, task_id)
        if self.idempotency is not None:
            for approval in task_approvals:
                action_id = approval.get("action_id")
                if action_id and approval.get("status") == "PENDING":
                    self.idempotency.set_status(namespace, f"approval-action:{action_id}", "CANCELLED")
        self.context.clear()
        return True, task

    def is_cancelled(self, namespace: str, task_id: str) -> bool:
        task = self.tasks.get(namespace, task_id)
        return bool(task and (task.get("cancellation_requested") or task.get("status") == "CANCELLED"))
