from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nexora.agents.registry import AgentRegistry
from nexora.database import SQLiteRepository
from nexora.integrations.telegram_runtime.services.approval_service import ApprovalService
from nexora.integrations.telegram_runtime.services.audit_service import AuditService
from nexora.integrations.telegram_runtime.services.task_service import TaskService
from nexora.security.audit.redaction import redact_text, sanitize_metadata
from nexora.security.policies import PolicyEngine
from nexora.skills import SkillRegistry, SkillRegistryError
from nexora.api.auth import APIKeyService
from nexora.collaboration import TeamAccessDenied, TeamService
from nexora.billing import BillingAccessDenied, BillingFoundation
from nexora.admin import AdminConsole
from nexora.metrics import MetricsService
from nexora.playground import PlaygroundService
from nexora.templates import TemplateApprovalRequired, TemplateRegistry, TemplateRegistryError
from nexora.webhooks import WebhookService, WebhookValidationError
from nexora.marketplace import MarketplaceError, MarketplaceService
from nexora.creators import CreatorError, CreatorService
from nexora.dashboard.runtime import DashboardTaskRuntime, DashboardTaskRuntimeError


TASK_STATUSES = {
    "NEW", "CLARIFYING", "QUEUED", "PLANNING", "IN_PROGRESS",
    "WAITING_APPROVAL", "COMPLETED", "FAILED", "CANCELLED", "EXPIRED",
}
AGENT_ACTIONS = {"enable", "disable", "reload"}
SKILL_ACTIONS = {"enable", "disable", "reload"}


class DashboardAPIError(RuntimeError):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class DashboardAPI:
    def __init__(
        self,
        database: SQLiteRepository,
        registry: AgentRegistry,
        policy: PolicyEngine,
        tasks: TaskService,
        approvals: ApprovalService,
        audit: AuditService,
        skills: SkillRegistry,
        api_keys: APIKeyService,
        webhooks: WebhookService,
        metrics: MetricsService,
        namespace: str,
        status_file: Path = Path("/workspace/.nexora-status/health.txt"),
        templates: TemplateRegistry | None = None,
        playground: PlaygroundService | None = None,
        teams: TeamService | None = None,
        billing: BillingFoundation | None = None,
        admin_console: AdminConsole | None = None,
        marketplace: MarketplaceService | None = None,
        creators: CreatorService | None = None,
        ecosystem: Any | None = None,
        task_runtime: DashboardTaskRuntime | None = None,
    ) -> None:
        self.database = database
        self.registry = registry
        self.policy = policy
        self.tasks = tasks
        self.approvals = approvals
        self.audit = audit
        self.skills = skills
        self.api_keys = api_keys
        self.webhooks = webhooks
        self.metrics = metrics
        self.namespace = namespace
        self.status_file = status_file
        self.templates = templates
        self.playground = playground
        self.teams = teams
        self.billing = billing
        self.admin_console = admin_console
        self.marketplace = marketplace
        self.creators = creators
        self.ecosystem = ecosystem
        self.task_runtime = task_runtime

    def health(self) -> dict[str, Any]:
        status = self._safe_status()
        registry = self.registry.health()
        return {
            "runtime": "OK" if self.database.check() else "ERROR",
            "telegram": self._health_value(status.get("telegram")),
            "database": "OK" if self.database.check() else "ERROR",
            "agents_loaded": int(registry["enabled"]),
            "skills": self.skills.health(),
            "templates": self.templates.health() if self.templates is not None else {"ok": False, "loaded": 0, "active": 0},
            "tenancy": {
                "organizations": len(self.teams.list_organizations(self.namespace)) if self.teams else 0,
                "workspaces": len(self.teams.list_workspaces(self.namespace)) if self.teams else 0,
            },
            "billing": "OK" if self.billing is not None else "WARNING",
            "marketplace": "OK" if self.marketplace is not None and self.database.schema_version() >= 8 else "ERROR",
            "creators": "OK" if self.creators is not None and self.database.schema_version() >= 9 else "ERROR",
            "agent_ecosystem": "OK" if self.ecosystem is not None and self.database.schema_version() >= 10 else "ERROR",
            "api": self._health_value(status.get("api")),
            "gateway": self._health_value(status.get("openclaw")),
            "web_runtime": "OK" if self.task_runtime is not None else "WARNING",
            "tasks": self.database.task_overview(self.namespace),
        }

    def agent_center(self, query: dict[str, str]) -> dict[str, Any]:
        workspace_id = self._workspace(query)
        return {"workspace_id": workspace_id, "agents": self.ecosystem.builder.list(self.namespace, workspace_id)}

    def agent_teams(self, query: dict[str, str]) -> dict[str, Any]:
        workspace_id = self._workspace(query)
        return {"workspace_id": workspace_id, "items": self.ecosystem.teams.list(self.namespace, workspace_id)}

    def agent_plans(self, query: dict[str, str]) -> dict[str, Any]:
        workspace_id = self._workspace(query)
        return {"workspace_id": workspace_id, "items": self.ecosystem.planning.list(self.namespace, workspace_id)}

    def agent_memory(self, query: dict[str, str]) -> dict[str, Any]:
        workspace_id = self._workspace(query)
        scope = str(query.get("scope") or "PERSONAL").upper()
        return {"workspace_id": workspace_id, "scope": scope, "items": self.ecosystem.memory.list(self.namespace, workspace_id, scope=scope, agent_id=query.get("agent_id"))}

    def agent_evaluations(self, query: dict[str, str]) -> dict[str, Any]:
        workspace_id = self._workspace(query)
        return {"workspace_id": workspace_id, "items": self.ecosystem.evaluation.list(self.namespace, workspace_id, query.get("agent_id"))}

    def sdk_overview(self) -> dict[str, Any]:
        return {"language": "python", "mode": "in-process", "arbitrary_code": False, "policy_checked": True, "operations": ["create_agent", "connect_skill", "create_team", "create_plan", "start_workflow", "result"]}

    def create_custom_agent(self, value: dict[str, Any], dashboard_session_id: str) -> dict[str, Any]:
        workspace_id = str(value.get("workspace_id") or "")
        manifest = value.get("manifest") if isinstance(value.get("manifest"), dict) else {}
        validated = self.ecosystem.builder.validate(manifest)
        approval_id = str(value.get("approval_id") or "")
        if not approval_id:
            approval = self._management_approval(dashboard_session_id, f"agent_builder:create:{workspace_id}:{validated['id']}:{validated['version']}", f"Create agent {validated['id']} {validated['version']}", "Agent manifest activation changes workspace capabilities.")
            return {"status": "WAITING_APPROVAL", **approval}
        result = self.ecosystem.builder.create(self.namespace, workspace_id, manifest, approval_id=approval_id)
        record = self.approvals.repository.get(self.namespace, approval_id)
        if record is not None:
            self._complete_management_task(str(record["task_id"]), f"Custom agent {validated['id']} created")
        return result

    def create_agent_team(self, value: dict[str, Any], dashboard_session_id: str) -> dict[str, Any]:
        workspace_id = str(value.get("workspace_id") or "")
        approval_id = str(value.get("approval_id") or "")
        if not approval_id:
            approval = self._management_approval(dashboard_session_id, f"agent_team:create:{workspace_id}", "Create agent team", "Team activation changes workspace orchestration.")
            return {"status": "WAITING_APPROVAL", **approval}
        result = self.ecosystem.teams.create(self.namespace, workspace_id, str(value.get("name") or ""), str(value.get("leader_agent_id") or ""), value.get("workflow") if isinstance(value.get("workflow"), list) else [], approval_id=approval_id)
        record = self.approvals.repository.get(self.namespace, approval_id)
        if record is not None:
            self._complete_management_task(str(record["task_id"]), f"Agent team {result['id']} created")
        return result

    def create_agent_plan(self, value: dict[str, Any]) -> dict[str, Any]:
        return self.ecosystem.planning.create(self.namespace, str(value.get("workspace_id") or ""), str(value.get("goal") or ""))

    def _workspace(self, query: dict[str, str]) -> str:
        if self.ecosystem is None:
            raise DashboardAPIError(503, "AGENT_ECOSYSTEM_UNAVAILABLE", "Agent ecosystem unavailable")
        workspace_id = str(query.get("workspace_id") or "")
        if not workspace_id:
            values = self.teams.list_workspaces(self.namespace) if self.teams else []
            if not values:
                raise DashboardAPIError(404, "WORKSPACE_NOT_FOUND", "Workspace not found or unavailable")
            workspace_id = str(values[0]["id"])
        return workspace_id

    def list_tasks(self, query: dict[str, str]) -> dict[str, Any]:
        status = query.get("status", "").upper() or None
        if status is not None and status not in TASK_STATUSES:
            raise DashboardAPIError(400, "INVALID_FILTER", "Некорректный статус задачи")
        try:
            limit = max(1, min(200, int(query.get("limit", "100"))))
        except ValueError:
            raise DashboardAPIError(400, "INVALID_FILTER", "Некорректный лимит") from None
        search = query.get("search", "").strip()[:100] or None
        return {"items": [self._safe_task(item) for item in self.database.list_tasks(self.namespace, limit=limit, status=status, search=search)]}

    def task_details(self, task_id: str) -> dict[str, Any]:
        task = self.database.get_task_details(self.namespace, task_id)
        if task is None:
            raise DashboardAPIError(404, "TASK_NOT_FOUND", "Задача не найдена или недоступна")
        task = self._safe_task(task)
        task["events"] = [self._safe_event(item) for item in task.get("events", [])]
        task["approvals"] = [
            {
                "id": item.get("id"),
                "action_type": redact_text(item.get("action_type"), 100),
                "status": item.get("status"),
                "expires_at": item.get("expires_at"),
                "used_at": item.get("used_at"),
            }
            for item in task.get("approvals", [])
        ]
        task["conversation"] = self.task_runtime.conversation(task_id) if self.task_runtime is not None else []
        task["downloads"] = ([{"id": "result", "name": f"{task_id}-result.txt", "type": "text/plain"}]
                             if task.get("result_summary") else [])
        return task

    def create_dashboard_task(self, value: dict[str, Any]) -> dict[str, Any]:
        runtime = self._task_runtime()
        try:
            task = runtime.create(self.namespace, value.get("message"), value.get("idempotency_key"))
        except DashboardTaskRuntimeError as exc:
            raise DashboardAPIError(exc.status, exc.code, exc.message) from exc
        stored = self.database.get_task_details(self.namespace, str(task["task_id"]))
        return self._safe_task(stored or {"id": task["task_id"], **task})

    def continue_dashboard_task(self, task_id: str, value: dict[str, Any]) -> dict[str, Any]:
        runtime = self._task_runtime()
        try:
            task = runtime.continue_task(self.namespace, task_id, value.get("message"), value.get("idempotency_key"))
        except DashboardTaskRuntimeError as exc:
            raise DashboardAPIError(exc.status, exc.code, exc.message) from exc
        stored = self.database.get_task_details(self.namespace, str(task["task_id"]))
        return self._safe_task(stored or {"id": task["task_id"], **task})

    def cancel_dashboard_task(self, task_id: str) -> dict[str, Any]:
        runtime = self._task_runtime()
        try:
            task = runtime.cancel(self.namespace, task_id)
        except DashboardTaskRuntimeError as exc:
            raise DashboardAPIError(exc.status, exc.code, exc.message) from exc
        stored = self.database.get_task_details(self.namespace, str(task["task_id"]))
        return self._safe_task(stored or {"id": task["task_id"], **task})

    def task_result_file(self, task_id: str) -> tuple[str, bytes]:
        task = self.database.get_task_details(self.namespace, task_id)
        if task is None:
            raise DashboardAPIError(404, "TASK_NOT_FOUND", "Задача не найдена или недоступна")
        result = redact_text(task.get("result_summary"), 100_000).strip()
        if not result:
            raise DashboardAPIError(404, "RESULT_NOT_FOUND", "Результат пока недоступен")
        title = redact_text(task.get("title"), 200)
        content = f"Nexora task {task_id}\nTitle: {title}\nStatus: {task.get('status')}\n\n{result}\n"
        return f"{task_id}-result.txt", content.encode("utf-8")

    def list_agents(self) -> dict[str, Any]:
        return {"items": [self._agent_card(manifest.id) for manifest in self.registry.all()]}

    def agent_details(self, agent_id: str) -> dict[str, Any]:
        manifest = self.registry.get(agent_id)
        if manifest is None:
            raise DashboardAPIError(404, "AGENT_NOT_FOUND", "Агент не найден")
        value = self._agent_card(manifest.id)
        value["description"] = manifest.description
        value["system_role"] = manifest.system_role
        value["approval_required"] = list(manifest.approval_required)
        value["recent_tasks"] = [self._safe_task(item) for item in self.database.list_agent_tasks(self.namespace, manifest.id, 10)]
        return value

    def list_skills(self) -> dict[str, Any]:
        return {"items": self.skills.list()}

    def skill_details(self, skill_id: str) -> dict[str, Any]:
        try:
            value = self.skills.info(skill_id)
        except SkillRegistryError as exc:
            raise DashboardAPIError(404, "SKILL_NOT_FOUND", "Skill не найден") from exc
        stored = self.database.get_skill_details(skill_id)
        if stored is None:
            raise DashboardAPIError(404, "SKILL_NOT_FOUND", "Skill не найден")
        value["events"] = [
            {
                "event": item.get("event"),
                "result": redact_text(item.get("result"), 80),
                "created_at": item.get("created_at"),
            }
            for item in stored.get("events", [])
        ]
        return value

    def list_templates(self) -> dict[str, Any]:
        if self.templates is None:
            raise DashboardAPIError(503, "TEMPLATES_UNAVAILABLE", "Templates are unavailable")
        return {"items": self.templates.list(), "installations": self.database.list_template_installations(self.namespace)}

    def template_details(self, template_id: str) -> dict[str, Any]:
        if self.templates is None:
            raise DashboardAPIError(503, "TEMPLATES_UNAVAILABLE", "Templates are unavailable")
        try:
            value = self.templates.info(template_id)
        except TemplateRegistryError as exc:
            raise DashboardAPIError(404, "TEMPLATE_NOT_FOUND", "Template not found or unavailable") from exc
        stored = self.database.get_template_details(template_id)
        value["events"] = [] if stored is None else stored.get("events", [])
        return value

    def request_template_install(self, template_id: str, dashboard_session_id: str) -> dict[str, Any]:
        details = self.template_details(template_id)
        if details["status"] != "ACTIVE":
            raise DashboardAPIError(409, "TEMPLATE_UNAVAILABLE", "Template is not active")
        if details["approval_required"] or details["risk"] == "MEDIUM":
            approval = self._management_approval(
                dashboard_session_id,
                f"template:install:{template_id}",
                f"Install template {template_id}",
                "The template requests reviewed capabilities and must be approved before activation.",
            )
            return {"status": "WAITING_APPROVAL", "template_id": template_id, **approval}
        try:
            result = self.templates.install(self.namespace, template_id)
        except (TemplateApprovalRequired, TemplateRegistryError) as exc:
            raise DashboardAPIError(403, "POLICY_DENIED", "Template installation denied") from exc
        return {"status": result["status"], "template_id": template_id, "installation_id": result["id"]}

    def playground_examples(self) -> dict[str, Any]:
        if self.playground is None:
            raise DashboardAPIError(503, "PLAYGROUND_UNAVAILABLE", "Playground is unavailable")
        return self.playground.examples()

    def list_organizations(self) -> dict[str, Any]:
        if self.teams is None:
            raise DashboardAPIError(503, "TEAMS_UNAVAILABLE", "Team layer unavailable")
        return {"items": self.teams.list_organizations(self.namespace)}

    def list_workspaces(self, query: dict[str, str]) -> dict[str, Any]:
        if self.teams is None:
            raise DashboardAPIError(503, "TEAMS_UNAVAILABLE", "Team layer unavailable")
        return {"items": self.teams.list_workspaces(self.namespace, query.get("organization_id") or None)}

    def list_members(self, query: dict[str, str]) -> dict[str, Any]:
        if self.teams is None:
            raise DashboardAPIError(503, "TEAMS_UNAVAILABLE", "Team layer unavailable")
        try:
            return {"items": self.teams.list_members(self.namespace, str(query.get("workspace_id") or ""))}
        except TeamAccessDenied as exc:
            raise DashboardAPIError(404, "WORKSPACE_NOT_FOUND", "Workspace not found or unavailable") from exc

    def list_knowledge(self, query: dict[str, str]) -> dict[str, Any]:
        if self.teams is None:
            raise DashboardAPIError(503, "TEAMS_UNAVAILABLE", "Team layer unavailable")
        try:
            return {"items": self.teams.list_knowledge(self.namespace, str(query.get("workspace_id") or ""))}
        except TeamAccessDenied as exc:
            raise DashboardAPIError(404, "WORKSPACE_NOT_FOUND", "Workspace not found or unavailable") from exc

    def list_plans(self) -> dict[str, Any]:
        if self.billing is None:
            raise DashboardAPIError(503, "BILLING_UNAVAILABLE", "Billing foundation unavailable")
        return {"items": self.billing.list_plans()}

    def billing_summary(self, query: dict[str, str]) -> dict[str, Any]:
        organization_id = self._tenant_organization(query)
        assert self.billing is not None
        try:
            return {"subscription": self.billing.subscription(self.namespace, organization_id), "limits": self.billing.limits(self.namespace, organization_id), "usage": self.billing.usage(self.namespace, organization_id)}
        except BillingAccessDenied as exc:
            raise DashboardAPIError(404, "ORGANIZATION_NOT_FOUND", "Organization not found or unavailable") from exc

    def usage_summary_v23(self, query: dict[str, str]) -> dict[str, Any]:
        organization_id = self._tenant_organization(query)
        assert self.billing is not None
        return self.billing.usage(self.namespace, organization_id)

    def limits_summary(self, query: dict[str, str]) -> dict[str, Any]:
        organization_id = self._tenant_organization(query)
        assert self.billing is not None
        return self.billing.limits(self.namespace, organization_id)

    def marketplace_catalog(self, query: dict[str, str]) -> dict[str, Any]:
        service = self._marketplace()
        return {"items": service.catalog(search=query.get("search") or None, category=query.get("category") or None, item_type=query.get("type") or None)}

    def marketplace_item(self, item_id: str) -> dict[str, Any]:
        try:
            return self._marketplace().item(item_id, include_manifest=True)
        except MarketplaceError as exc:
            raise DashboardAPIError(404, "MARKETPLACE_ITEM_NOT_FOUND", "Marketplace item not found or unavailable") from exc

    def marketplace_my_items(self) -> dict[str, Any]:
        return {"items": self._marketplace().my_items(self.namespace), "publishers": self.database.list_publishers(self.namespace)}

    def creator_dashboard(self) -> dict[str, Any]:
        service = self._creators()
        try:
            profile = service.my_profile(self.namespace)
            return {"configured": True, "profile": profile, "packages": service.packages(self.namespace), "analytics": service.analytics(self.namespace)}
        except CreatorError as exc:
            if exc.code == "CREATOR_NOT_FOUND":
                return {"configured": False, "profile": None, "packages": [], "analytics": {}}
            raise DashboardAPIError(403, exc.code, "Creator dashboard unavailable") from exc

    def create_creator_profile(self, value: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._creators().create_profile(self.namespace, str(value.get("display_name") or ""), str(value.get("bio") or ""), str(value.get("avatar_reference") or "") or None)
        except CreatorError as exc:
            raise DashboardAPIError(400, exc.code, "Creator profile rejected") from exc

    def create_creator_draft(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value.get("manifest"), dict):
            raise DashboardAPIError(400, "CREATOR_MANIFEST_INVALID", "Manifest is required")
        try:
            return self._creators().create_draft(self.namespace, value["manifest"], str(value.get("changelog") or ""))
        except CreatorError as exc:
            raise DashboardAPIError(400, exc.code, "Creator package rejected") from exc

    def creator_version_action(self, package_id: str, version: str, action: str) -> dict[str, Any]:
        service = self._creators()
        try:
            if action == "submit":
                return service.submit(self.namespace, package_id, version)
            if action == "validate":
                return service.validate_version(self.namespace, package_id, version)
            if action == "publish":
                return service.publish(self.namespace, package_id, version)
        except CreatorError as exc:
            raise DashboardAPIError(409, exc.code, "Creator package action denied") from exc
        raise DashboardAPIError(400, "CREATOR_ACTION_INVALID", "Creator action is invalid")

    def register_publisher(self, value: dict[str, Any], session_id: str) -> dict[str, Any]:
        try:
            publisher = self._marketplace().register_publisher(self.namespace, str(value.get("display_name") or ""))
        except MarketplaceError as exc:
            raise DashboardAPIError(400, exc.code, "Publisher registration failed") from exc
        approval = self._management_approval(session_id, f"marketplace:publisher_verify:{publisher['id']}", f"Verify publisher {publisher['display_name']}", "Publisher verification grants package submission rights; code execution remains forbidden.")
        return {"publisher": publisher, "status": "WAITING_APPROVAL", **approval}

    def publish_marketplace(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value.get("manifest"), dict):
            raise DashboardAPIError(400, "MARKETPLACE_MANIFEST_INVALID", "Manifest is required")
        try:
            return self._marketplace().publish(self.namespace, str(value.get("publisher_id") or ""), value["manifest"], str(value["signature"]) if value.get("signature") else None)
        except MarketplaceError as exc:
            raise DashboardAPIError(400 if "INVALID" in exc.code or "FORBIDDEN" in exc.code else 403, exc.code, "Marketplace package rejected") from exc

    def request_marketplace_install(self, item_id: str, value: dict[str, Any], session_id: str) -> dict[str, Any]:
        workspace_id = str(value.get("workspace_id") or "")
        version = str(value.get("version") or "") or None
        if not workspace_id:
            raise DashboardAPIError(400, "VALIDATION_ERROR", "workspace_id is required")
        try:
            return self._marketplace().install(self.namespace, workspace_id, item_id, version=version)
        except MarketplaceError as exc:
            if exc.code != "MARKETPLACE_APPROVAL_REQUIRED":
                status = 404 if exc.code in {"MARKETPLACE_ITEM_NOT_FOUND", "MARKETPLACE_RESOURCE_NOT_FOUND"} else 403
                raise DashboardAPIError(status, exc.code, "Marketplace installation denied") from exc
            details = self.marketplace_item(item_id)
            selected = version or details["version"]
            approval = self._management_approval(session_id, f"marketplace:install:{workspace_id}:{item_id}:{selected}", f"Install marketplace item {item_id} {selected}", "Reviewed permissions will be activated only inside the selected workspace.")
            return {"item_id": item_id, "workspace_id": workspace_id, "version": selected, "status": "WAITING_APPROVAL", **approval}

    def admin_summary(self) -> dict[str, Any]:
        if self.admin_console is None:
            raise DashboardAPIError(503, "ADMIN_UNAVAILABLE", "Admin console unavailable")
        try:
            return self.admin_console.summary(self.namespace)
        except BillingAccessDenied as exc:
            raise DashboardAPIError(403, "ACCESS_DENIED", "Admin access denied") from exc

    def request_plan_change(self, organization_id: str, plan_id: str, session_id: str) -> dict[str, Any]:
        if self.admin_console is None or self.billing is None:
            raise DashboardAPIError(503, "ADMIN_UNAVAILABLE", "Admin console unavailable")
        if self.database.get_organization(organization_id) is None:
            raise DashboardAPIError(404, "ORGANIZATION_NOT_FOUND", "Organization not found")
        try:
            self.billing.plans.require(plan_id)
        except ValueError as exc:
            raise DashboardAPIError(404, "PLAN_NOT_FOUND", "Plan not found") from exc
        approval = self._management_approval(session_id, f"billing:plan_change:{organization_id}:{plan_id}", f"Change organization plan to {plan_id}", "Plan changes affect tenant limits. No payment is executed.")
        return {"status": "WAITING_APPROVAL", "organization_id": organization_id, "plan_id": plan_id, **approval}

    def request_organization_block(self, organization_id: str, blocked: bool, session_id: str) -> dict[str, Any]:
        if self.admin_console is None or self.database.get_organization(organization_id) is None:
            raise DashboardAPIError(404, "ORGANIZATION_NOT_FOUND", "Organization not found")
        action = "block" if blocked else "unblock"
        approval = self._management_approval(session_id, f"billing:organization_{action}:{organization_id}", f"{action.title()} organization", "Organization access will change after approval.")
        return {"status": "WAITING_APPROVAL", "organization_id": organization_id, "action": action, **approval}

    def request_agent_action(self, agent_id: str, action: str, dashboard_session_id: str) -> dict[str, Any]:
        manifest = self.registry.get(agent_id)
        if manifest is None or action not in AGENT_ACTIONS:
            raise DashboardAPIError(404, "ACTION_NOT_FOUND", "Действие недоступно")
        decision = self.policy.evaluate(
            "orchestrator",
            risk="HIGH",
            action_type="configuration_changes",
            approval_granted=False,
        )
        if not decision.requires_approval:
            raise DashboardAPIError(403, "POLICY_DENIED", "Действие запрещено политикой")

        task = self.tasks.create(
            self.namespace,
            f"Dashboard: {action} agent {manifest.id}",
            f"dashboard-{dashboard_session_id[:24]}",
        )
        task = self.tasks.update_fields(self.namespace, task["task_id"], assigned_agent="Orchestrator")
        approval = self.approvals.create(
            self.namespace,
            task["task_id"],
            f"dashboard-{dashboard_session_id[:24]}",
            f"agent:{action}:{manifest.id}",
            f"{action.title()} {manifest.name}",
            "Изменение доступности агента влияет на маршрутизацию новых задач.",
        )
        self.tasks.update_fields(self.namespace, task["task_id"], pending_approval_id=approval["approval_id"])
        self.tasks.transition(self.namespace, task["task_id"], "WAITING_APPROVAL", event="DASHBOARD_APPROVAL_REQUIRED")
        self.audit.record(
            "AGENT_CHANGE_REQUESTED",
            source="dashboard_api",
            action_result="WAITING_APPROVAL",
            task_id=task["task_id"],
            approval_id=approval["approval_id"],
            agent=manifest.id,
            action=action,
        )
        return {
            "status": "WAITING_APPROVAL",
            "task_id": task["task_id"],
            "approval_id": approval["approval_id"],
        }

    def request_skill_action(self, skill_id: str, action: str, dashboard_session_id: str) -> dict[str, Any]:
        try:
            skill = self.skills.info(skill_id)
        except SkillRegistryError as exc:
            raise DashboardAPIError(404, "SKILL_NOT_FOUND", "Skill не найден") from exc
        if action not in SKILL_ACTIONS:
            raise DashboardAPIError(404, "ACTION_NOT_FOUND", "Действие недоступно")
        decision = self.policy.evaluate(
            "orchestrator",
            risk="HIGH",
            action_type="configuration_changes",
            approval_granted=False,
        )
        if not decision.requires_approval:
            raise DashboardAPIError(403, "POLICY_DENIED", "Действие запрещено политикой")
        task = self.tasks.create(
            self.namespace,
            f"Dashboard: {action} skill {skill_id}",
            f"dashboard-{dashboard_session_id[:24]}",
        )
        task = self.tasks.update_fields(self.namespace, task["task_id"], assigned_agent="Orchestrator")
        approval = self.approvals.create(
            self.namespace,
            task["task_id"],
            f"dashboard-{dashboard_session_id[:24]}",
            f"skill:{action}:{skill_id}",
            f"{action.title()} {skill['name']}",
            "Изменение lifecycle skill влияет на доступные способности агентов.",
        )
        self.tasks.update_fields(self.namespace, task["task_id"], pending_approval_id=approval["approval_id"])
        self.tasks.transition(self.namespace, task["task_id"], "WAITING_APPROVAL", event="SKILL_APPROVAL_REQUIRED")
        self.audit.record(
            "SKILL_CHANGE_REQUESTED",
            source="dashboard_api",
            action_result="WAITING_APPROVAL",
            task_id=task["task_id"],
            approval_id=approval["approval_id"],
            skill_id=skill_id,
            action=action,
        )
        return {"status": "WAITING_APPROVAL", "task_id": task["task_id"], "approval_id": approval["approval_id"]}

    def list_api_keys(self) -> dict[str, Any]:
        return {"items": self.api_keys.list(self.namespace)}

    def request_api_key_create(self, value: dict[str, Any], dashboard_session_id: str) -> dict[str, Any]:
        try:
            name = str(value.get("name") or "")
            scopes = value.get("scopes") if isinstance(value.get("scopes"), list) else []
            expires_at = str(value.get("expires_at")) if value.get("expires_at") else None
            key_id = self.api_keys.request_key(self.namespace, name, scopes, expires_at)
        except (TypeError, ValueError) as exc:
            raise DashboardAPIError(400, "VALIDATION_ERROR", "Некорректные параметры API key") from exc
        approval = self._management_approval(
            dashboard_session_id,
            f"api-key:create:{key_id}",
            "Create API key",
            "Ключ предоставит внешний доступ только к выбранным scopes.",
        )
        self.database.attach_api_key_approval(key_id, approval["approval_id"])
        return {"status": "WAITING_APPROVAL", "key_id": key_id, **approval}

    def request_api_key_action(self, key_id: str, action: str, dashboard_session_id: str) -> dict[str, Any]:
        record = self.database.get_api_key_record(key_id)
        if record is None or record.get("owner") != self.namespace or action not in {"disable", "delete"}:
            raise DashboardAPIError(404, "API_KEY_NOT_FOUND", "API key не найден")
        approval = self._management_approval(
            dashboard_session_id,
            f"api-key:{action}:{key_id}",
            f"{action.title()} API key",
            "Изменение немедленно влияет на авторизацию внешних клиентов.",
        )
        self.database.attach_api_key_approval(key_id, approval["approval_id"])
        return {"status": "WAITING_APPROVAL", "key_id": key_id, **approval}

    def list_webhooks(self) -> dict[str, Any]:
        return {"items": self.webhooks.list(self.namespace)}

    def request_webhook_create(self, value: dict[str, Any], dashboard_session_id: str) -> dict[str, Any]:
        try:
            url = str(value.get("url") or "")
            events = value.get("events") if isinstance(value.get("events"), list) else []
            webhook_id = self.webhooks.request_webhook(self.namespace, url, [str(item) for item in events])
        except (TypeError, ValueError, WebhookValidationError) as exc:
            raise DashboardAPIError(400, "VALIDATION_ERROR", "Некорректный webhook") from exc
        approval = self._management_approval(
            dashboard_session_id,
            f"webhook:activate:{webhook_id}",
            "Activate webhook",
            "Webhook будет получать выбранные события по HTTPS.",
        )
        self.database.attach_webhook_approval(webhook_id, approval["approval_id"])
        return {"status": "WAITING_APPROVAL", "webhook_id": webhook_id, **approval}

    def request_webhook_action(self, webhook_id: str, action: str, dashboard_session_id: str) -> dict[str, Any]:
        record = self.database.get_webhook_record(webhook_id)
        if record is None or record.get("owner") != self.namespace or action not in {"disable", "delete"}:
            raise DashboardAPIError(404, "WEBHOOK_NOT_FOUND", "Webhook не найден")
        approval = self._management_approval(
            dashboard_session_id,
            f"webhook:{action}:{webhook_id}",
            f"{action.title()} webhook",
            "Изменение влияет на доставку внешних событий.",
        )
        self.database.attach_webhook_approval(webhook_id, approval["approval_id"])
        return {"status": "WAITING_APPROVAL", "webhook_id": webhook_id, **approval}

    def metrics_summary(self) -> dict[str, Any]:
        value = self.metrics.summary(self.namespace)
        value["active_agents"] = sum(1 for item in self.list_agents()["items"] if item["enabled"])
        value["community"] = self.metrics.community_summary(self.namespace)
        return value

    @staticmethod
    def integrations() -> dict[str, Any]:
        return {
            "items": [
                {"id": "github-integration", "status": "READY", "mode": "READ_ONLY", "writes": False},
                {"id": "content-platform", "status": "READY", "mode": "DRAFT_AND_APPROVAL", "auto_publish": False},
            ]
        }

    def list_approvals(self, query: dict[str, str]) -> dict[str, Any]:
        status = query.get("status", "").upper() or None
        items = self.approvals.repository.list(self.namespace, status=status, limit=100)
        safe = []
        for item in items:
            safe.append(
                {
                    "id": item.get("approval_id"),
                    "task_id": item.get("task_id"),
                    "action_type": item.get("action_type"),
                    "action_summary": redact_text(item.get("action_summary"), 200),
                    "risk_summary": redact_text(item.get("risk_summary"), 300),
                    "status": item.get("status"),
                    "created_at": item.get("created_at"),
                    "expires_at": item.get("expires_at"),
                    "used_at": item.get("used_at"),
                }
            )
        return {"items": safe}

    def decide_approval(self, approval_id: str, decision: str) -> dict[str, Any]:
        if decision not in {"approve", "reject"}:
            raise DashboardAPIError(400, "INVALID_DECISION", "Некорректное решение")
        approval = self.approvals.repository.get(self.namespace, approval_id)
        if approval is None:
            raise DashboardAPIError(404, "APPROVAL_NOT_FOUND", "Подтверждение не найдено или недоступно")
        status, updated = self.approvals.decide(
            self.namespace,
            approval_id,
            str(approval.get("session_id") or ""),
            decision,
        )
        if status in {"NOT_FOUND", "ALREADY_USED", "INVALID"}:
            raise DashboardAPIError(409, "APPROVAL_UNAVAILABLE", "Подтверждение уже использовано или недоступно")
        if status == "EXPIRED":
            task = self.tasks.get(self.namespace, str(approval["task_id"]))
            if task is not None and task.get("status") == "WAITING_APPROVAL":
                self.tasks.transition(self.namespace, task["task_id"], "EXPIRED", event="APPROVAL_EXPIRED")
            raise DashboardAPIError(409, "APPROVAL_EXPIRED", "Подтверждение истекло")
        assert updated is not None
        task_id = str(updated["task_id"])
        if status == "REJECTED":
            rejected_action = str(approval.get("action_type") or "")
            if rejected_action.startswith("api-key:create:"):
                self.database.cancel_pending_api_key(rejected_action.split(":", 2)[2])
            elif rejected_action.startswith("webhook:activate:"):
                self.database.cancel_pending_webhook(rejected_action.split(":", 2)[2])
            task = self.tasks.get(self.namespace, task_id)
            if task is not None and task.get("status") == "WAITING_APPROVAL":
                self.tasks.update_fields(self.namespace, task_id, pending_approval_id=None)
                self.tasks.transition(self.namespace, task_id, "CANCELLED", event="APPROVAL_REJECTED")
            if str(approval.get("action_type") or "").startswith("dashboard-task:") and self.task_runtime is not None:
                self.task_runtime.context.clear()
            self.audit.record("APPROVAL_DECISION", source="dashboard_api", action_result="REJECTED", approval_id=approval_id, task_id=task_id)
            return {"status": "REJECTED", "task_id": task_id}

        action_type = str(updated.get("action_type") or "")
        one_time_secret: str | None = None
        if action_type.startswith("dashboard-task:"):
            if self.task_runtime is None or not self.task_runtime.resume_approved(self.namespace, task_id):
                raise DashboardAPIError(409, "TASK_RESUME_FAILED", "Не удалось продолжить задачу")
            execution = "QUEUED"
        elif action_type.startswith("agent:"):
            self._execute_agent_action(action_type, approval_id, task_id)
            execution = "COMPLETED"
        elif action_type.startswith("skill:"):
            self._execute_skill_action(action_type, approval_id, task_id)
            execution = "COMPLETED"
        elif action_type.startswith("template:"):
            self._execute_template_action(action_type, approval_id, task_id)
            execution = "COMPLETED"
        elif action_type.startswith("api-key:"):
            one_time_secret = self._execute_api_key_action(action_type, task_id, approval_id)
            execution = "COMPLETED"
        elif action_type.startswith("webhook:"):
            one_time_secret = self._execute_webhook_action(action_type, task_id, approval_id)
            execution = "COMPLETED"
        elif action_type.startswith("billing:"):
            self._execute_billing_action(action_type, task_id, approval_id)
            execution = "COMPLETED"
        elif action_type.startswith("marketplace:"):
            self._execute_marketplace_action(action_type, task_id, approval_id)
            execution = "COMPLETED"
        else:
            execution = "TELEGRAM_RUNTIME_PENDING"
        self.audit.record("APPROVAL_DECISION", source="dashboard_api", action_result="APPROVED", approval_id=approval_id, task_id=task_id)
        response = {"status": "APPROVED", "task_id": task_id, "execution": execution}
        if one_time_secret is not None:
            response["one_time_secret"] = one_time_secret
            response["secret_notice"] = "Показано один раз. Сохраните в защищённом хранилище."
        return response

    def _task_runtime(self) -> DashboardTaskRuntime:
        if self.task_runtime is None:
            raise DashboardAPIError(503, "DASHBOARD_RUNTIME_UNAVAILABLE", "Веб-исполнитель временно недоступен")
        return self.task_runtime

    def audit_events(self, query: dict[str, str]) -> dict[str, Any]:
        try:
            limit = max(1, min(200, int(query.get("limit", "100"))))
        except ValueError:
            raise DashboardAPIError(400, "INVALID_FILTER", "Некорректный лимит") from None
        severity = query.get("severity", "").upper() or None
        if severity and severity not in {"INFO", "WARNING", "SECURITY", "ERROR"}:
            raise DashboardAPIError(400, "INVALID_FILTER", "Некорректный severity")
        rows = self.database.list_audit(
            limit=limit,
            severity=severity,
            source=query.get("source", "")[:100] or None,
            event=query.get("event", "")[:100] or None,
            date_prefix=query.get("date", "")[:10] or None,
        )
        return {"items": [self._safe_audit(row) for row in rows]}

    def audit_access(self, path: str, result: str = "ALLOWED") -> None:
        self.audit.record("API_ACCESS", source="dashboard_api", action_result=result, endpoint=path[:160])

    def _execute_marketplace_action(self, action_type: str, task_id: str, approval_id: str) -> None:
        service = self._marketplace()
        if action_type.startswith("marketplace:publisher_verify:"):
            publisher_id = action_type.split(":", 2)[2]
            service.verify_publisher(self.namespace, publisher_id, approval_id)
            summary = f"Publisher {publisher_id} verified"
        elif action_type.startswith("marketplace:install:"):
            parts = action_type.split(":", 5)
            if len(parts) != 5:
                raise DashboardAPIError(409, "ACTION_INVALID", "Marketplace action is invalid")
            _, _, workspace_id, item_id, version = parts
            service.install(self.namespace, workspace_id, item_id, version=version, approval_id=approval_id)
            summary = f"Marketplace item {item_id} {version} installed"
        else:
            raise DashboardAPIError(409, "ACTION_INVALID", "Marketplace action is invalid")
        self.tasks.update_fields(self.namespace, task_id, pending_approval_id=None, result_summary=summary)
        self.tasks.transition(self.namespace, task_id, "COMPLETED", event="MARKETPLACE_ACTION_COMPLETED")

    def _marketplace(self) -> MarketplaceService:
        if self.marketplace is None:
            raise DashboardAPIError(503, "MARKETPLACE_UNAVAILABLE", "Marketplace unavailable")
        return self.marketplace

    def _creators(self) -> CreatorService:
        if self.creators is None:
            raise DashboardAPIError(503, "CREATOR_UNAVAILABLE", "Creator service unavailable")
        return self.creators

    def _execute_agent_action(self, action_type: str, approval_id: str, task_id: str) -> None:
        parts = action_type.split(":", 2)
        if len(parts) != 3 or parts[1] not in AGENT_ACTIONS or self.registry.get(parts[2]) is None:
            raise DashboardAPIError(409, "ACTION_INVALID", "Действие не может быть выполнено")
        _, action, agent_id = parts
        policy = self.policy.evaluate(
            "orchestrator",
            risk="HIGH",
            action_type="configuration_changes",
            approval_granted=True,
        )
        if not policy.allowed:
            raise DashboardAPIError(403, "POLICY_DENIED", "Действие запрещено политикой")
        if action == "enable":
            self.database.set_agent_override(agent_id, True, approval_id)
        elif action == "disable":
            self.database.set_agent_override(agent_id, False, approval_id)
        else:
            self.registry.load()
        self.tasks.update_fields(
            self.namespace,
            task_id,
            pending_approval_id=None,
            result_summary=f"Agent action {action} completed for {agent_id}",
        )
        self.tasks.transition(self.namespace, task_id, "COMPLETED", event="AGENT_CONFIGURATION_CHANGED")

    def _execute_skill_action(self, action_type: str, approval_id: str, task_id: str) -> None:
        parts = action_type.split(":", 2)
        if len(parts) != 3 or parts[1] not in SKILL_ACTIONS or self.skills.get(parts[2]) is None:
            raise DashboardAPIError(409, "ACTION_INVALID", "Действие не может быть выполнено")
        _, action, skill_id = parts
        policy = self.policy.evaluate(
            "orchestrator",
            risk="HIGH",
            action_type="configuration_changes",
            approval_granted=True,
        )
        if not policy.allowed:
            raise DashboardAPIError(403, "POLICY_DENIED", "Действие запрещено политикой")
        try:
            if action == "enable":
                self.skills.enable(skill_id, approval_id=approval_id)
            elif action == "disable":
                self.skills.disable(skill_id, approval_id=approval_id)
            else:
                self.skills.reload(skill_id, approval_id=approval_id)
        except (SkillRegistryError, KeyError, ValueError) as exc:
            self.audit.record(
                "SKILL_FAILED",
                severity="ERROR",
                source="dashboard_api",
                action_result="SKILL_VALIDATION_FAILED",
                skill_id=skill_id,
            )
            raise DashboardAPIError(409, "SKILL_VALIDATION_FAILED", "Skill не прошёл проверку") from exc
        self.tasks.update_fields(
            self.namespace,
            task_id,
            pending_approval_id=None,
            result_summary=f"Skill action {action} completed for {skill_id}",
        )
        self.tasks.transition(self.namespace, task_id, "COMPLETED", event="SKILL_CONFIGURATION_CHANGED")

    def _execute_template_action(self, action_type: str, approval_id: str, task_id: str) -> None:
        parts = action_type.split(":", 2)
        if self.templates is None or len(parts) != 3 or parts[1] != "install" or self.templates.get(parts[2]) is None:
            raise DashboardAPIError(409, "ACTION_INVALID", "Template action is unavailable")
        template_id = parts[2]
        try:
            result = self.templates.install(self.namespace, template_id, approval_id=approval_id)
        except (TemplateApprovalRequired, TemplateRegistryError, KeyError, ValueError) as exc:
            raise DashboardAPIError(409, "TEMPLATE_INSTALL_FAILED", "Template installation failed safely") from exc
        self.tasks.update_fields(
            self.namespace,
            task_id,
            pending_approval_id=None,
            result_summary=f"Template {template_id} installed as {result['id']}",
        )
        self.tasks.transition(self.namespace, task_id, "COMPLETED", event="TEMPLATE_INSTALLED")

    def _execute_api_key_action(self, action_type: str, task_id: str, approval_id: str) -> str | None:
        _, action, key_id = action_type.split(":", 2)
        if action == "create":
            secret = self.api_keys.activate(key_id, approval_id)
        elif action == "disable":
            self.api_keys.disable(self.namespace, key_id, approval_id)
            secret = None
        elif action == "delete":
            self.api_keys.delete(self.namespace, key_id, approval_id)
            secret = None
        else:
            raise DashboardAPIError(409, "ACTION_INVALID", "Действие недоступно")
        self._complete_management_task(task_id, f"API key action {action} completed")
        self.audit.record("API_KEY_CHANGED", source="dashboard_api", action_result=action.upper(), key_id=key_id, task_id=task_id)
        return secret

    def _execute_webhook_action(self, action_type: str, task_id: str, approval_id: str) -> str | None:
        _, action, webhook_id = action_type.split(":", 2)
        if action == "activate":
            secret = self.webhooks.activate(webhook_id, approval_id)
        elif action == "disable":
            self.webhooks.disable(self.namespace, webhook_id, approval_id)
            secret = None
        elif action == "delete":
            self.webhooks.delete(self.namespace, webhook_id, approval_id)
            secret = None
        else:
            raise DashboardAPIError(409, "ACTION_INVALID", "Действие недоступно")
        self._complete_management_task(task_id, f"Webhook action {action} completed")
        self.audit.record("WEBHOOK_CHANGED", source="dashboard_api", action_result=action.upper(), webhook_id=webhook_id, task_id=task_id)
        return secret

    def _execute_billing_action(self, action_type: str, task_id: str, approval_id: str) -> None:
        if self.admin_console is None:
            raise DashboardAPIError(503, "ADMIN_UNAVAILABLE", "Admin console unavailable")
        parts = action_type.split(":")
        try:
            if len(parts) == 4 and parts[1] == "plan_change":
                self.admin_console.change_plan(self.namespace, parts[2], parts[3], approval_id)
                summary = f"Plan changed to {parts[3]} for {parts[2]}"
            elif len(parts) == 3 and parts[1] in {"organization_block", "organization_unblock"}:
                self.admin_console.block(self.namespace, parts[2], parts[1] == "organization_block", approval_id)
                summary = f"Organization access updated for {parts[2]}"
            else:
                raise DashboardAPIError(409, "ACTION_INVALID", "Billing action invalid")
        except BillingAccessDenied as exc:
            raise DashboardAPIError(403, "BILLING_ACTION_DENIED", "Billing action denied") from exc
        self._complete_management_task(task_id, summary)

    def _tenant_organization(self, query: dict[str, str]) -> str:
        if self.billing is None or self.teams is None:
            raise DashboardAPIError(503, "BILLING_UNAVAILABLE", "Billing foundation unavailable")
        requested = str(query.get("organization_id") or "")
        organizations = self.teams.list_organizations(self.namespace)
        if not organizations:
            raise DashboardAPIError(404, "ORGANIZATION_NOT_FOUND", "Organization not found")
        organization_id = requested or str(organizations[0]["id"])
        if organization_id not in {str(item["id"]) for item in organizations}:
            raise DashboardAPIError(404, "ORGANIZATION_NOT_FOUND", "Organization not found or unavailable")
        return organization_id

    def _management_approval(self, session_id: str, action_type: str, summary: str, risk: str) -> dict[str, str]:
        policy = self.policy.evaluate("orchestrator", risk="HIGH", action_type="configuration_changes", approval_granted=False)
        if not policy.requires_approval:
            raise DashboardAPIError(403, "POLICY_DENIED", "Действие запрещено политикой")
        task = self.tasks.create(self.namespace, summary, f"dashboard-{session_id[:24]}")
        approval = self.approvals.create(
            self.namespace, task["task_id"], f"dashboard-{session_id[:24]}", action_type, summary, risk,
        )
        self.tasks.update_fields(self.namespace, task["task_id"], pending_approval_id=approval["approval_id"])
        self.tasks.transition(self.namespace, task["task_id"], "WAITING_APPROVAL", event="MANAGEMENT_APPROVAL_REQUIRED")
        self.audit.record("MANAGEMENT_CHANGE_REQUESTED", source="dashboard_api", action_result="WAITING_APPROVAL", task_id=task["task_id"], approval_id=approval["approval_id"], action_type=action_type)
        return {"task_id": task["task_id"], "approval_id": approval["approval_id"]}

    def _complete_management_task(self, task_id: str, summary: str) -> None:
        policy = self.policy.evaluate("orchestrator", risk="HIGH", action_type="configuration_changes", approval_granted=True)
        if not policy.allowed:
            raise DashboardAPIError(403, "POLICY_DENIED", "Действие запрещено политикой")
        self.tasks.update_fields(self.namespace, task_id, pending_approval_id=None, result_summary=summary)
        self.tasks.transition(self.namespace, task_id, "COMPLETED", event="MANAGEMENT_CONFIGURATION_CHANGED")

    def _agent_card(self, agent_id: str) -> dict[str, Any]:
        manifest = self.registry.require(agent_id)
        override = self.database.get_agent_override(agent_id)
        enabled = manifest.enabled if override is None else override
        recent = self.database.list_agent_tasks(self.namespace, agent_id, 20)
        running = any(item.get("status") in {"NEW", "QUEUED", "PLANNING", "IN_PROGRESS"} for item in recent)
        return {
            "id": manifest.id,
            "name": manifest.name,
            "status": "ONLINE" if enabled and running else ("IDLE" if enabled else "DISABLED"),
            "enabled": enabled,
            "tools": list(manifest.tools_allowed),
            "permissions": list(manifest.permissions),
            "restrictions": list(manifest.restrictions),
            "risk": manifest.risk_level,
        }

    def _safe_status(self) -> dict[str, str]:
        allowed = {"openclaw", "telegram", "api"}
        result: dict[str, str] = {}
        try:
            for line in self.status_file.read_text(encoding="utf-8").splitlines():
                key, separator, value = line.partition("=")
                if separator and key in allowed:
                    result[key] = value[:40]
        except OSError:
            pass
        return result

    @staticmethod
    def _health_value(value: str | None) -> str:
        return "OK" if str(value or "").casefold() in {"ok", "healthy", "connected", "available"} else "WARNING"

    @staticmethod
    def _safe_event(item: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = json.loads(str(item.get("payload") or "{}"))
        except json.JSONDecodeError:
            payload = {}
        return {
            "id": item.get("id"),
            "type": item.get("event_type"),
            "metadata": sanitize_metadata(payload if isinstance(payload, dict) else {}),
            "created_at": item.get("created_at"),
        }

    @staticmethod
    def _safe_task(item: dict[str, Any]) -> dict[str, Any]:
        safe = dict(item)
        if "title" in safe:
            safe["title"] = redact_text(safe.get("title"), 200)
        if "result_summary" in safe:
            safe["result_summary"] = redact_text(safe.get("result_summary"), 1500)
        return safe

    @staticmethod
    def _safe_audit(item: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = json.loads(str(item.get("payload") or "{}"))
        except json.JSONDecodeError:
            payload = {}
        return {
            "event": item.get("event"),
            "severity": item.get("severity"),
            "source": item.get("source"),
            "result": item.get("action_result"),
            "hash": str(item.get("hash") or "")[:16],
            "metadata": sanitize_metadata(payload if isinstance(payload, dict) else {}),
            "created_at": item.get("created_at"),
        }
