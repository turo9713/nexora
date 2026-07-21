from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from nexora.runtime.orchestrator import Orchestrator
from nexora.agents.registry import AgentRegistry
from nexora.database import SQLiteRepository
from nexora.runtime.events import EventBus, SQLiteEventSink
from nexora.security.policies import PolicyEngine

from .commands.approvals import approval_decision_message, approval_keyboard
from .commands.cancel import cancel_response
from .commands.history import history_response
from .commands.menu import menu_response
from .commands.newtask import approval_requirement, is_forbidden, normalize_description
from .commands.reset import reset_response
from .commands.status import status_response
from .commands.task_details import task_details_response
from .formatter import (
    format_agents,
    format_approval_request,
    format_health,
    format_platform_health,
    format_help,
    format_history_v14,
    format_task_status,
    format_welcome,
)
from .keyboards import BUTTON_TO_COMMAND, main_reply_markup
from .security.access_control import AccessControl
from .security.callback_validation import parse_approval_callback
from .services.approval_service import ApprovalService
from .services.audit_service import AuditService
from .services.cancellation_service import CancellationService
from .services.execution_service import ExecutionService, Notifier
from .services.idempotency_service import IdempotencyService
from .services.health_service import HealthService
from .services.task_service import TaskService
from .storage.action_repository import ActionRepository
from .storage.approval_repository import ApprovalRepository
from .storage.audit_repository import AuditRepository
from .storage.context_repository import ContextRepository
from .storage.task_repository import TaskRepository


BASE_PATH = Path("/workspace/nexora")
STATE_PATH = BASE_PATH / "runtime" / "state" / "telegram_v14"
CONTEXT_PATH = BASE_PATH / "runtime" / "state" / "telegram_sessions"
HEALTH_PATH = Path("/workspace/.nexora-status/health.txt")
WORKFLOW_NAME = "development_flow"
MAX_TASK_LENGTH = 2000
MIN_MESSAGE_INTERVAL_SECONDS = 0.4
BUSY_STATUSES = {"NEW", "QUEUED", "PLANNING", "IN_PROGRESS"}


NEW_TASK_HINT = (
    "Отправь описание новой задачи одним сообщением.\n"
    "Например:\n"
    "Создай план Telegram-бота для учёта расходов"
)


@dataclass(frozen=True)
class HandlerResponse:
    text: str | None = None
    reply_markup: dict[str, Any] | None = None
    chat_id: int | None = None
    callback_query_id: str | None = None
    callback_answer: str | None = None
    callback_alert: bool = False


class TelegramRuntimeHandlers:
    def __init__(
        self,
        owner_id: int,
        namespace_key: bytes,
        orchestrator: Orchestrator | None = None,
        notifier: Notifier | None = None,
        state_path: Path = STATE_PATH,
        context_path: Path = CONTEXT_PATH,
    ) -> None:
        self.owner_id = owner_id
        self.orchestrator = orchestrator or Orchestrator(str(BASE_PATH))
        self.access = AccessControl(owner_id, namespace_key)
        self.namespace = self.access.owner_namespace
        self.context = ContextRepository(root=context_path)
        self.database = SQLiteRepository(state_path.parent / "database" / "nexora.sqlite3")
        self.database.migrate()
        self.database.import_task_directory(state_path / "tasks")
        self.registry = AgentRegistry(BASE_PATH / "agents").load()
        self.policy = PolicyEngine(self.registry, BASE_PATH, status_resolver=self.database.agent_enabled)
        self.events = EventBus([SQLiteEventSink(self.database)])
        self.tasks = TaskService(
            TaskRepository(state_path / "tasks"),
            database=self.database,
            event_bus=self.events,
        )
        self.approvals = ApprovalService(
            ApprovalRepository(state_path / "approvals"),
            database=self.database,
            event_bus=self.events,
        )
        self.actions = ActionRepository(state_path / "actions")
        self.idempotency = IdempotencyService(self.actions)
        self.audit = AuditService(AuditRepository(state_path / "audit"), database=self.database)
        self.health = HealthService(self.database, self.registry, state_path)
        self.cancellations = CancellationService(
            self.tasks,
            self.approvals,
            self.context,
            self.idempotency,
        )
        self._notifier = notifier or (lambda text, markup=None: None)
        self.execution = ExecutionService(
            self.orchestrator,
            self.tasks,
            self.context,
            self.cancellations,
            self.idempotency,
            self.audit,
            WORKFLOW_NAME,
            self._notifier,
            event_bus=self.events,
            execution_guard=self._runtime_policy_allowed,
        )
        self._awaiting_task = False
        self._last_message_at = 0.0

    def handle_update(self, update: dict[str, Any]) -> HandlerResponse | None:
        owner_event = self.access.is_owner_message(update) or self.access.is_owner_callback(update)
        namespace = self.namespace if owner_event else self.access.security_namespace
        update_id = update.get("update_id")
        update_key = f"telegram-update:{update_id}" if isinstance(update_id, int) else None
        if update_key and not self.idempotency.begin(namespace, update_key, "telegram_update"):
            return None
        try:
            if "callback_query" in update:
                response = self._handle_callback(update)
            else:
                response = self._handle_message(update)
            if update_key:
                self.idempotency.set_status(namespace, update_key, "SUCCEEDED")
            return response
        except Exception as exc:
            if update_key:
                self.idempotency.set_status(namespace, update_key, "FAILED")
            self.audit.record("HANDLER_ERROR", error_type=type(exc).__name__, error=exc)
            if owner_event:
                return HandlerResponse(
                    "Не удалось обработать запрос.\nКод: NX_INTERNAL_ERROR",
                    main_reply_markup(),
                    self.owner_id,
                )
            return None

    def _handle_message(self, update: dict[str, Any]) -> HandlerResponse | None:
        if not self.access.is_owner_message(update):
            self.audit.record("ACCESS_DENIED", surface="telegram_message")
            self.events.publish("SECURITY_DENIED", metadata={"surface": "telegram_message", "reason": "allowlist"})
            recipient = self.access.denied_message_recipient(update)
            return HandlerResponse("ACCESS_DENIED", None, recipient) if recipient is not None else None

        message = update.get("message") or {}
        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            return self._owner_response("Поддерживаются только текстовые команды.")

        now = time.monotonic()
        if now - self._last_message_at < MIN_MESSAGE_INTERVAL_SECONDS:
            return self._owner_response("Слишком много запросов. Повтори чуть позже.")
        self._last_message_at = now

        normalized = BUTTON_TO_COMMAND.get(text.strip(), text.strip())
        if len(normalized) > MAX_TASK_LENGTH:
            return self._owner_response("Сообщение слишком длинное. Максимум 2000 символов.")

        if normalized.startswith("/"):
            command, _, argument = normalized.partition(" ")
            command = command.split("@", 1)[0].lower()
            return self._handle_command(command, argument.strip())

        if self._awaiting_task:
            self._awaiting_task = False
            return self._start_task(normalized)
        if self.context.active_task_id():
            return self._continue_task(normalized)
        if self._looks_like_expense(normalized):
            return self._start_task(normalized)
        return self._owner_response(format_help())

    def _handle_command(self, command: str, argument: str) -> HandlerResponse:
        if command in {"/start", "/menu"}:
            self._awaiting_task = False
            text, markup = menu_response()
            return HandlerResponse(format_welcome() if command == "/start" else text, markup, self.owner_id)
        if command == "/help":
            return self._owner_response(format_help())
        if command == "/status":
            return self._owner_response(status_response(self.tasks, self.context, self.namespace))
        if command in {"/history", "/tasks"}:
            return self._owner_response(history_response(self.tasks, self.namespace, argument))
        if command == "/results":
            completed = [task for task in self.tasks.history(self.namespace, 20) if task.get("status") == "COMPLETED"][:5]
            return self._owner_response(format_history_v14(completed))
        if command == "/task":
            return self._owner_response(task_details_response(self.tasks, self.namespace, argument))
        if command == "/newtask":
            self.context.clear()
            if argument:
                return self._start_task(argument)
            self._awaiting_task = True
            return self._owner_response(NEW_TASK_HINT)
        if command == "/cancel":
            self._awaiting_task = False
            return self._owner_response(cancel_response(self.cancellations, self.context, self.namespace))
        if command == "/reset":
            self._awaiting_task = False
            return self._owner_response(reset_response(self.context))
        if command == "/health":
            return self._owner_response(format_platform_health(self.health.snapshot(self.namespace)))
        if command == "/agents":
            workflow = self.orchestrator.workflows.load_workflow(WORKFLOW_NAME)
            return self._owner_response(format_agents(workflow.get("route", [])))
        return self._owner_response(format_help())

    def _start_task(self, description: str) -> HandlerResponse:
        description = normalize_description(description)
        if not description:
            return self._owner_response("Описание задачи не может быть пустым.")
        if is_forbidden(description):
            self.audit.record("TASK_REJECTED", code="NX_PERMISSION_DENIED")
            return self._owner_response("Задача отклонена политикой безопасности.\nКод: NX_PERMISSION_DENIED")
        if not self._runtime_policy_allowed():
            self.audit.record("SECURITY_DENIED", surface="agent_route", code="NX_PERMISSION_DENIED")
            self.events.publish("SECURITY_DENIED", metadata={"surface": "agent_route", "reason": "policy"})
            return self._owner_response("Задача отклонена политикой безопасности.\nКод: NX_PERMISSION_DENIED")

        self.context.clear()
        session = self.context.new()
        task = self.tasks.create(self.namespace, description, session["session_id"])
        session = self.context.set_active_task(session, task["task_id"])
        session = self.context.add_turn(session, "user", description)
        self.context.save(session)

        requirement = approval_requirement(description)
        if requirement is not None:
            approval = self.approvals.create(
                self.namespace,
                task["task_id"],
                session["session_id"],
                requirement.action_type,
                requirement.summary,
                requirement.risk,
            )
            approval_action_key = f"approval-action:{approval['action_id']}"
            self.idempotency.begin(
                self.namespace,
                approval_action_key,
                requirement.action_type,
                task_id=task["task_id"],
                action_id=approval["action_id"],
            )
            self.idempotency.set_status(self.namespace, approval_action_key, "PENDING")
            self.tasks.update_fields(self.namespace, task["task_id"], pending_approval_id=approval["approval_id"])
            self.tasks.transition(self.namespace, task["task_id"], "WAITING_APPROVAL", event="APPROVAL_REQUIRED")
            self.audit.record("APPROVAL_CREATED", task_id=task["task_id"], approval_id=approval["approval_id"])
            return HandlerResponse(
                format_approval_request(approval),
                approval_keyboard(approval["approval_id"]),
                self.owner_id,
            )

        if not self.execution.submit(self.namespace, task["task_id"], session["session_id"]):
            return self._owner_response("Задача уже поставлена в очередь. Повторный запуск заблокирован.")
        queued = self.tasks.get(self.namespace, task["task_id"])
        return self._owner_response(format_task_status(queued))

    def _continue_task(self, description: str) -> HandlerResponse:
        description = normalize_description(description)
        if is_forbidden(description):
            return self._owner_response("Сообщение отклонено политикой безопасности.\nКод: NX_PERMISSION_DENIED")
        if not self._runtime_policy_allowed():
            return self._owner_response("Продолжение отклонено политикой безопасности.\nКод: NX_PERMISSION_DENIED")
        session = self.context.load()
        task_id = self.context.active_task_id()
        task = self.tasks.get(self.namespace, task_id) if task_id else None
        if session is None or task is None:
            self.context.clear()
            return self._owner_response("Диалог завершён или истёк. Используй /newtask для новой задачи.")
        if task.get("status") in BUSY_STATUSES:
            return self._owner_response("Задача ещё выполняется. Используй /status и дождись завершения этапа.")
        if task.get("status") == "WAITING_APPROVAL":
            return self._owner_response("Задача ожидает подтверждения. Используй кнопки под сообщением с предупреждением.")
        if task.get("status") in {"CANCELLED", "FAILED", "EXPIRED"}:
            return self._owner_response("Эта задача больше не активна. Используй /newtask для новой задачи.")
        if not description:
            return self._owner_response("Ответ не может быть пустым.")
        session = self.context.add_turn(session, "user", description)
        self.context.save(session)
        if not self.execution.submit(self.namespace, task["task_id"], session["session_id"]):
            return self._owner_response("Повторный запуск заблокирован политикой идемпотентности.")
        queued = self.tasks.get(self.namespace, task["task_id"])
        return self._owner_response(format_task_status(queued))

    def _handle_callback(self, update: dict[str, Any]) -> HandlerResponse | None:
        callback = update.get("callback_query")
        if not isinstance(callback, dict):
            return None
        callback_id = str(callback.get("id") or "")[:128]
        if not self.access.is_owner_callback(update):
            self.audit.record("ACCESS_DENIED", surface="telegram_callback")
            self.events.publish("SECURITY_DENIED", metadata={"surface": "telegram_callback", "reason": "allowlist"})
            return HandlerResponse(
                callback_query_id=callback_id,
                callback_answer="ACCESS_DENIED",
                callback_alert=True,
            )
        parsed = parse_approval_callback(str(callback.get("data") or ""))
        if parsed is None:
            return HandlerResponse(
                callback_query_id=callback_id,
                callback_answer="Некорректное действие.",
                callback_alert=True,
            )
        decision, approval_id = parsed
        session = self.context.load()
        if session is None:
            status, approval = "NOT_FOUND", None
        else:
            status, approval = self.approvals.decide(
                self.namespace,
                approval_id,
                str(session["session_id"]),
                decision,
            )
        message = approval_decision_message(status)
        if approval is not None and status == "APPROVED":
            task_id = str(approval["task_id"])
            approval_action_key = f"approval-action:{approval['action_id']}"
            task = self.tasks.get(self.namespace, task_id)
            if task is None or task.get("pending_approval_id") != approval_id:
                status = "NOT_FOUND"
                message = approval_decision_message(status)
            else:
                self.tasks.update_fields(self.namespace, task_id, pending_approval_id=None)
                if not self.execution.submit(self.namespace, task_id, str(session["session_id"])):
                    status = "ALREADY_USED"
                    message = approval_decision_message(status)
                    self.idempotency.set_status(self.namespace, approval_action_key, "FAILED")
                else:
                    self.idempotency.set_status(self.namespace, approval_action_key, "SUCCEEDED")
        elif approval is not None and status == "REJECTED":
            self.idempotency.set_status(
                self.namespace,
                f"approval-action:{approval['action_id']}",
                "CANCELLED",
            )
            self.cancellations.cancel(self.namespace, str(approval["task_id"]))
        elif approval is not None and status == "EXPIRED":
            self.idempotency.set_status(
                self.namespace,
                f"approval-action:{approval['action_id']}",
                "CANCELLED",
            )
            task_id = str(approval["task_id"])
            task = self.tasks.get(self.namespace, task_id)
            if task is not None and task.get("status") == "WAITING_APPROVAL":
                self.tasks.update_fields(self.namespace, task_id, pending_approval_id=None)
                self.tasks.transition(self.namespace, task_id, "EXPIRED", event="APPROVAL_EXPIRED")
                self.context.clear()
        self.audit.record("APPROVAL_DECISION", approval_id=approval_id, status=status)
        return HandlerResponse(
            text=message,
            reply_markup=main_reply_markup(),
            chat_id=self.owner_id,
            callback_query_id=callback_id,
            callback_answer=message.splitlines()[0],
        )

    def _owner_response(self, text: str, markup: dict[str, Any] | None = None) -> HandlerResponse:
        return HandlerResponse(text, markup or main_reply_markup(), self.owner_id)

    def _looks_like_expense(self, text: str) -> bool:
        lowered = text.casefold()
        has_amount = any(token.isdigit() for token in lowered.replace(",", " ").split())
        markers = ("руб", "₽", "expense", "расход", "потрат", "купил", "оплат", "такси", "обед", "еда", "кофе")
        return has_amount and any(marker in lowered for marker in markers)

    def _read_health(self) -> dict[str, str]:
        allowed = {"openclaw", "model", "telegram", "last_successful_check_utc"}
        if not HEALTH_PATH.is_file():
            return {}
        result: dict[str, str] = {}
        try:
            for line in HEALTH_PATH.read_text(encoding="utf-8").splitlines():
                key, separator, value = line.partition("=")
                if separator and key in allowed:
                    result[key] = value
        except OSError:
            return {}
        return result

    def reconcile_external_approval(self) -> bool:
        """Resume an active Telegram task approved through the dashboard."""
        session = self.context.load()
        if session is None:
            return False
        task_id = self.context.active_task_id()
        task = self.tasks.get(self.namespace, task_id) if task_id else None
        if task is None or task.get("status") != "WAITING_APPROVAL":
            return False
        approval_id = task.get("pending_approval_id")
        if not isinstance(approval_id, str):
            return False
        approval = self.approvals.repository.get(self.namespace, approval_id)
        if approval is None or approval.get("status") != "APPROVED":
            return False
        action_key = f"approval-action:{approval['action_id']}"
        self.tasks.update_fields(self.namespace, task_id, pending_approval_id=None)
        if not self.execution.submit(self.namespace, task_id, str(session["session_id"])):
            self.idempotency.set_status(self.namespace, action_key, "FAILED")
            return False
        self.idempotency.set_status(self.namespace, action_key, "SUCCEEDED")
        self.audit.record("APPROVAL_RESUMED", source="telegram_runtime", action_result="STARTED", task_id=task_id, approval_id=approval_id)
        return True

    def _runtime_policy_allowed(self) -> bool:
        try:
            workflow = self.orchestrator.workflows.load_workflow(WORKFLOW_NAME)
            route = workflow.get("route", [])
            if not isinstance(route, list):
                return False
            return self.policy.authorize_route([str(agent) for agent in route]).allowed
        except Exception:
            return False

    def close(self) -> None:
        self.execution.shutdown()
