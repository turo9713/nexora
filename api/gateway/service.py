from __future__ import annotations

from typing import Any

from nexora.api.auth import APIKeyPrincipal
from nexora.api.schemas import APIValidationError, validate_task_create, validate_webhook_create
from nexora.security.audit.redaction import redact_text
from nexora.skills import SkillRegistryError
from nexora.templates import TemplateApprovalRequired, TemplateRegistryError


class APIGatewayError(RuntimeError):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class APIGateway:
    """Authorized facade over task services; it has no provider or Gateway transport."""

    def __init__(self, database: Any, agents: Any, skills: Any, templates: Any, playground: Any, policy: Any, tasks: Any, approvals: Any, webhooks: Any, metrics: Any) -> None:
        self.database = database
        self.agents = agents
        self.skills = skills
        self.templates = templates
        self.playground = playground
        self.policy = policy
        self.tasks = tasks
        self.approvals = approvals
        self.webhooks = webhooks
        self.metrics = metrics

    def health(self) -> dict[str, str]:
        return {"status": "ok" if self.database.check() and self.skills.health()["ok"] and self.templates.health()["ok"] else "degraded", "version": "v1"}

    def create_task(self, principal: APIKeyPrincipal, value: dict[str, Any], request_id: str) -> dict[str, Any]:
        try:
            payload = validate_task_create(value)
        except APIValidationError as exc:
            raise APIGatewayError(400, "VALIDATION_ERROR", "Некорректный запрос задачи") from exc
        decision = self.policy.evaluate(payload["agent"], risk="LOW", action_type="api_task_create")
        if not decision.allowed:
            raise APIGatewayError(403, "POLICY_DENIED", "Действие запрещено политикой")
        try:
            skill = self.skills.require_active(payload["skill"])
        except SkillRegistryError as exc:
            raise APIGatewayError(403, "SKILL_UNAVAILABLE", "Skill недоступен") from exc
        if skill.agent != payload["agent"]:
            raise APIGatewayError(403, "SKILL_AGENT_MISMATCH", "Skill недоступен выбранному агенту")
        task = self.tasks.create(principal.owner, payload["title"], f"api-{request_id[:24]}")
        task = self.tasks.update_fields(principal.owner, task["task_id"], assigned_agent=payload["agent"].title())
        task = self.tasks.transition(principal.owner, task["task_id"], "QUEUED", stage="Ожидание обработки API", progress=25, event="API_QUEUED")
        self.metrics.task_created(principal.owner, payload["agent"], payload["skill"])
        return {"task_id": task["task_id"], "status": task["status"]}

    def list_tasks(self, principal: APIKeyPrincipal, query: dict[str, str]) -> dict[str, Any]:
        try:
            limit = max(1, min(100, int(query.get("limit", "50"))))
        except ValueError as exc:
            raise APIGatewayError(400, "VALIDATION_ERROR", "Некорректный лимит") from exc
        return {"items": [self._task(item) for item in self.database.list_tasks(principal.owner, limit=limit)]}

    def get_task(self, principal: APIKeyPrincipal, task_id: str) -> dict[str, Any]:
        value = self.database.get_task_details(principal.owner, task_id)
        if value is None:
            raise APIGatewayError(404, "TASK_NOT_FOUND", "Задача не найдена или недоступна")
        return self._task(value)

    def list_agents(self) -> dict[str, Any]:
        items = []
        for manifest in self.agents.all():
            override = self.database.get_agent_override(manifest.id)
            enabled = manifest.enabled if override is None else override
            items.append({"id": manifest.id, "status": "ACTIVE" if enabled else "DISABLED"})
        return {"items": items}

    def list_skills(self) -> dict[str, Any]:
        return {"items": [{"id": item["id"], "version": item["version"], "agent": item["agent"], "status": item["status"]} for item in self.skills.list()]}

    def list_templates(self) -> dict[str, Any]:
        return {"items": self.templates.list()}

    def get_template(self, template_id: str) -> dict[str, Any]:
        try:
            return self.templates.info(template_id)
        except TemplateRegistryError as exc:
            raise APIGatewayError(404, "TEMPLATE_NOT_FOUND", "Template not found or unavailable") from exc

    def install_template(self, principal: APIKeyPrincipal, template_id: str, request_id: str) -> dict[str, Any]:
        try:
            manifest = self.templates.info(template_id)
        except TemplateRegistryError as exc:
            raise APIGatewayError(404, "TEMPLATE_NOT_FOUND", "Template not found or unavailable") from exc
        if manifest["status"] != "ACTIVE":
            raise APIGatewayError(409, "TEMPLATE_UNAVAILABLE", "Template is not active")
        if manifest["approval_required"] or manifest["risk"] == "MEDIUM":
            task = self.tasks.create(principal.owner, f"Install template {template_id}", f"api-{request_id[:24]}")
            approval = self.approvals.create(
                principal.owner,
                task["task_id"],
                f"api-{request_id[:24]}",
                f"template:install:{template_id}",
                f"Install template {template_id}",
                "The template requests reviewed capabilities and must be approved before activation.",
            )
            self.tasks.update_fields(principal.owner, task["task_id"], pending_approval_id=approval["approval_id"])
            self.tasks.transition(principal.owner, task["task_id"], "WAITING_APPROVAL", event="TEMPLATE_APPROVAL_REQUIRED")
            return {"template_id": template_id, "status": "WAITING_APPROVAL", "task_id": task["task_id"], "approval_id": approval["approval_id"]}
        try:
            record = self.templates.install(principal.owner, template_id)
        except (TemplateApprovalRequired, TemplateRegistryError) as exc:
            raise APIGatewayError(403, "POLICY_DENIED", "Template installation denied") from exc
        return {"template_id": template_id, "status": record["status"], "installation_id": record["id"]}

    def playground_examples(self) -> dict[str, Any]:
        return self.playground.examples()

    def request_webhook(self, principal: APIKeyPrincipal, value: dict[str, Any], request_id: str) -> dict[str, Any]:
        try:
            payload = validate_webhook_create(value)
            webhook_id = self.webhooks.request_webhook(principal.owner, payload["url"], payload["events"])
        except (APIValidationError, ValueError) as exc:
            raise APIGatewayError(400, "VALIDATION_ERROR", "Некорректный webhook") from exc
        task = self.tasks.create(principal.owner, "API webhook registration", f"api-{request_id[:24]}")
        approval = self.approvals.create(
            principal.owner,
            task["task_id"],
            f"api-{request_id[:24]}",
            f"webhook:activate:{webhook_id}",
            "Activate external webhook",
            "Webhook будет получать выбранные события Nexora по HTTPS.",
        )
        self.database.attach_webhook_approval(webhook_id, approval["approval_id"])
        self.tasks.update_fields(principal.owner, task["task_id"], pending_approval_id=approval["approval_id"])
        self.tasks.transition(principal.owner, task["task_id"], "WAITING_APPROVAL", event="WEBHOOK_APPROVAL_REQUIRED")
        return {"webhook_id": webhook_id, "status": "WAITING_APPROVAL", "approval_id": approval["approval_id"]}

    def list_webhooks(self, principal: APIKeyPrincipal) -> dict[str, Any]:
        return {"items": self.webhooks.list(principal.owner)}

    @staticmethod
    def _task(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "task_id": item.get("id") or item.get("task_id"),
            "title": redact_text(item.get("title"), 200),
            "status": item.get("status"),
            "progress": int(item.get("progress") or 0),
            "agent": item.get("agent") or item.get("assigned_agent"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
            "completed_at": item.get("completed_at"),
            "result_summary": redact_text(item.get("result_summary"), 1000),
            "error_code": item.get("error_code"),
        }
