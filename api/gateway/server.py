from __future__ import annotations

import json
import re
import ssl
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from nexora.agents.registry import AgentRegistry
from nexora.agents import AgentEcosystem
from nexora.api.auth import APIKeyService
from nexora.api.gateway.service import APIGateway, APIGatewayError
from nexora.api.middleware import request_context
from nexora.api.rate_limit import APIRateLimiter
from nexora.collaboration import TeamService
from nexora.billing import BillingFoundation
from nexora.database import SQLiteRepository
from nexora.integrations.telegram_runtime.services.approval_service import ApprovalService
from nexora.integrations.telegram_runtime.services.audit_service import AuditService
from nexora.integrations.telegram_runtime.services.task_service import TaskService
from nexora.integrations.telegram_runtime.storage.approval_repository import ApprovalRepository
from nexora.integrations.telegram_runtime.storage.audit_repository import AuditRepository
from nexora.integrations.telegram_runtime.storage.task_repository import TaskRepository
from nexora.metrics import MetricsService
from nexora.playground import PlaygroundService
from nexora.runtime.events import EventBus, SQLiteEventSink
from nexora.security.policies import PolicyEngine
from nexora.skills import SkillRegistry
from nexora.templates import TemplateRegistry
from nexora.webhooks import WebhookService
from nexora.marketplace import MarketplaceService
from nexora.creators import CreatorService
from nexora.operations import OperationsService
from nexora.enterprise import EnterpriseService
from nexora.workforce import AIWorkforceService


MAX_BODY = 32 * 1024
TASK_ID = re.compile(r"^[A-Za-z0-9-]{3,100}$")
AGENT_ID = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
ROUTES = {
    ("POST", "/api/v1/tasks"): ("tasks:create", 10),
    ("GET", "/api/v1/tasks"): ("tasks:read", 60),
    ("GET", "/api/v1/agents"): ("agents:read", 60),
    ("GET", "/api/v1/agents/status"): ("agents:read", 60),
    ("GET", "/api/v1/dashboard"): ("operations:read", 60),
    ("GET", "/api/v1/activity"): ("operations:read", 60),
    ("GET", "/api/v1/notifications"): ("notifications:read", 60),
    ("GET", "/api/v1/skills"): ("skills:read", 60),
    ("GET", "/api/v1/templates"): ("templates:read", 60),
    ("GET", "/api/v1/playground/examples"): ("playground:read", 60),
    ("GET", "/api/v1/organizations"): ("organizations:read", 60),
    ("GET", "/api/v1/workspaces"): ("workspaces:read", 60),
    ("POST", "/api/v1/workspaces"): ("workspaces:write", 10),
    ("GET", "/api/v1/members"): ("members:read", 60),
    ("POST", "/api/v1/invite"): ("members:invite", 10),
    ("GET", "/api/v1/knowledge"): ("knowledge:read", 60),
    ("POST", "/api/v1/knowledge"): ("knowledge:write", 10),
    ("GET", "/api/v1/plans"): ("plans:read", 60),
    ("GET", "/api/v1/subscription"): ("billing:read", 60),
    ("GET", "/api/v1/usage"): ("usage:read", 60),
    ("GET", "/api/v1/limits"): ("limits:read", 60),
    ("GET", "/api/v1/marketplace"): ("marketplace:read", 60),
    ("GET", "/api/v1/workforce"): ("marketplace:read", 60),
    ("GET", "/api/v1/workforce/team"): ("marketplace:read", 60),
    ("POST", "/api/v1/marketplace/publish"): ("marketplace:publish", 10),
    ("GET", "/api/v1/creator/packages"): ("creator:read", 60),
    ("GET", "/api/v1/creator/analytics"): ("creator:read", 60),
    ("GET", "/api/v1/agent-definitions"): ("agent_ecosystem:read", 60),
    ("POST", "/api/v1/agent-definitions"): ("agent_ecosystem:manage", 10),
    ("GET", "/api/v1/agent-teams"): ("agent_ecosystem:read", 60),
    ("POST", "/api/v1/agent-teams"): ("agent_ecosystem:manage", 10),
    ("GET", "/api/v1/agent-plans"): ("agent_ecosystem:read", 60),
    ("POST", "/api/v1/agent-plans"): ("agent_ecosystem:manage", 10),
    ("GET", "/api/v1/agent-memory"): ("agent_ecosystem:read", 60),
    ("GET", "/api/v1/agent-evaluations"): ("agent_ecosystem:read", 60),
    ("GET", "/api/v1/sdk"): ("agent_ecosystem:read", 60),
    ("POST", "/api/v1/webhooks"): ("webhooks:manage", 10),
    ("GET", "/api/v1/webhooks"): ("webhooks:manage", 30),
    ("GET", "/api/v1/policies"): ("enterprise:read", 60),
    ("GET", "/api/v1/security/events"): ("enterprise:read", 60),
    ("GET", "/api/v1/sla"): ("enterprise:read", 60),
    ("GET", "/api/v1/storage/health"): ("enterprise:read", 60),
}


@dataclass(frozen=True)
class PublicAPIConfig:
    host: str = "0.0.0.0"
    port: int = 18881
    project_root: Path = Path("/workspace/nexora")
    state_root: Path = Path("/workspace/nexora/runtime/state/telegram_v14")
    database_path: Path = Path("/workspace/nexora/runtime/state/database/nexora.sqlite3")
    webhook_master_file: Path = Path("/run/secrets/api_webhook_master")
    agent_memory_key_file: Path = Path("/run/secrets/agent_memory_key")
    tls_cert_file: Path | None = Path("/run/secrets/api_tls_cert")
    tls_key_file: Path | None = Path("/run/secrets/api_tls_key")


@dataclass
class PublicAPIApplication:
    gateway: APIGateway
    keys: APIKeyService
    rate_limiter: APIRateLimiter
    audit: AuditService
    metrics: MetricsService


def _secret(path: Path, minimum: int = 32) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("API secret unavailable")
    value = path.read_bytes().strip()
    if len(value) < minimum:
        raise RuntimeError("API secret invalid")
    return value


def create_application(config: PublicAPIConfig) -> PublicAPIApplication:
    database = SQLiteRepository(config.database_path)
    database.migrate()
    agents = AgentRegistry(config.project_root / "agents").load()
    policy = PolicyEngine(agents, config.project_root, status_resolver=database.agent_enabled)
    audit = AuditService(AuditRepository(config.state_root / "audit"), database=database)
    skills = SkillRegistry(
        config.project_root / "skills" / "manifests",
        database=database,
        audit=audit,
        agent_registry=agents,
        platform_version="3.0.0",
    ).load()
    events = EventBus([SQLiteEventSink(database)])
    tasks = TaskService(TaskRepository(config.state_root / "tasks"), database=database, event_bus=events)
    approvals = ApprovalService(ApprovalRepository(config.state_root / "approvals"), database=database, event_bus=events)
    webhooks = WebhookService(database, _secret(config.webhook_master_file), audit=audit)
    metrics = MetricsService(database)
    templates = TemplateRegistry(config.project_root / "templates", database=database, agents=agents, skills=skills, policy=policy, audit=audit, metrics=metrics).load()
    playground = PlaygroundService(audit)
    teams = TeamService(database, policy, audit)
    billing = BillingFoundation(database, audit)
    marketplace = MarketplaceService(database, teams, policy, audit)
    workforce = AIWorkforceService(marketplace)
    creators = CreatorService(database, marketplace, teams, policy, audit)
    ecosystem = AgentEcosystem(database, teams, policy, audit, memory_pepper=_secret(config.agent_memory_key_file))
    operations = OperationsService(database, teams, agents, billing)
    enterprise = EnterpriseService(database, teams, policy, audit, agents, config.state_root)
    gateway = APIGateway(database, agents, skills, templates, playground, teams, billing, marketplace, creators, policy, tasks, approvals, webhooks, metrics, ecosystem, operations, enterprise, workforce)
    return PublicAPIApplication(gateway, APIKeyService(database), APIRateLimiter(), audit, metrics)


def create_server(config: PublicAPIConfig, *, use_tls: bool = True) -> ThreadingHTTPServer:
    application = create_application(config)

    class Handler(PublicAPIRequestHandler):
        app = application

    server = ThreadingHTTPServer((config.host, config.port), Handler)
    server.daemon_threads = True
    if use_tls:
        if config.tls_cert_file is None or config.tls_key_file is None:
            raise RuntimeError("API TLS required")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(config.tls_cert_file, config.tls_key_file)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


class PublicAPIRequestHandler(BaseHTTPRequestHandler):
    app: PublicAPIApplication
    server_version = "NexoraAPI/3.5"
    sys_version = ""

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        context = request_context(self.headers.get("X-Request-ID"), self.headers.get("X-Correlation-ID"))
        if path == "/healthz" and method == "GET":
            self._json(200, self.app.gateway.health(), context)
            return
        route = ROUTES.get((method, path))
        task_events_match = re.fullmatch(r"/api/v1/tasks/([^/]+)/events", path) if method == "GET" else None
        task_match = re.fullmatch(r"/api/v1/tasks/([^/]+)", path) if method == "GET" else None
        agent_match = re.fullmatch(r"/api/v1/agents/([^/]+)", path) if method == "GET" else None
        template_match = re.fullmatch(r"/api/v1/templates/([^/]+)", path)
        marketplace_match = re.fullmatch(r"/api/v1/marketplace/([a-z0-9][a-z0-9-]{1,62})(?:/(install))?", path)
        workforce_match = re.fullmatch(r"/api/v1/workforce/([a-z0-9][a-z0-9-]{1,62})(?:/(install|update|uninstall|integration))?", path)
        creator_match = re.fullmatch(r"/api/v1/creators/(CRT-[A-F0-9]{12})", path)
        if route is None and task_events_match and TASK_ID.fullmatch(task_events_match.group(1)):
            route = ("tasks:read", 60)
        if route is None and task_match and TASK_ID.fullmatch(task_match.group(1)):
            route = ("tasks:read", 60)
        if route is None and agent_match and AGENT_ID.fullmatch(agent_match.group(1)):
            route = ("agents:read", 60)
        if route is None and template_match and TASK_ID.fullmatch(template_match.group(1)):
            route = ("templates:install" if method == "POST" else "templates:read", 10 if method == "POST" else 60)
        if route is None and marketplace_match:
            route = ("marketplace:install" if method == "POST" else "marketplace:read", 10 if method == "POST" else 60)
        if route is None and workforce_match:
            route = ("marketplace:install" if method == "POST" else "marketplace:read", 10 if method == "POST" else 60)
        if route is None and creator_match and method == "GET":
            route = ("creators:read", 60)
        if route is None:
            if path.startswith("/api/"):
                self.app.audit.record("API_DENIED", severity="SECURITY", source="public_api", action_result="NOT_FOUND", request_id=context.request_id, correlation_id=context.correlation_id, method=method, endpoint=path)
            self._json(404, {"error": "NOT_FOUND"}, context)
            return
        scope, limit = route
        rate_limit_path = path
        if task_events_match:
            rate_limit_path = "/api/v1/tasks/{id}/events"
        elif task_match:
            rate_limit_path = "/api/v1/tasks/{id}"
        self.app.audit.record("API_REQUEST", source="public_api", action_result="RECEIVED", request_id=context.request_id, correlation_id=context.correlation_id, method=method, endpoint=path)
        bearer = self._bearer()
        principal = self.app.keys.authenticate(bearer) if bearer else None
        if principal is None:
            self.app.audit.record("API_DENIED", severity="SECURITY", source="public_api", action_result="DENIED", request_id=context.request_id, correlation_id=context.correlation_id, endpoint=path, reason="authentication_or_scope")
            self.app.metrics.api_request(None, path, False)
            self._json(401, {"error": "UNAUTHORIZED"}, context)
            return
        if not principal.allows(scope):
            self.app.audit.record("API_DENIED", severity="SECURITY", source="public_api", action_result="SCOPE_DENIED", request_id=context.request_id, correlation_id=context.correlation_id, endpoint=path, key_id=principal.key_id)
            self.app.metrics.api_request(principal.owner, path, False)
            self._json(403, {"error": "SCOPE_DENIED"}, context)
            return
        if not self.app.rate_limiter.allow(principal.key_id, principal.owner, rate_limit_path, limit=limit):
            self.app.audit.record("API_RATE_LIMITED", source="public_api", action_result="RATE_LIMITED", request_id=context.request_id, correlation_id=context.correlation_id, endpoint=path, key_id=principal.key_id)
            self.app.metrics.api_request(principal.owner, path, False)
            self._json(429, {"error": "RATE_LIMIT_EXCEEDED"}, context)
            return
        try:
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            if method == "POST" and path == "/api/v1/tasks":
                response = self.app.gateway.create_task(principal, self._body(), context.request_id)
                status = 202
            elif method == "GET" and path == "/api/v1/tasks":
                response = self.app.gateway.list_tasks(principal, query)
                status = 200
            elif method == "GET" and path == "/api/v1/dashboard":
                response = self.app.gateway.operations_dashboard(principal, query)
                status = 200
            elif method == "GET" and path == "/api/v1/activity":
                response = self.app.gateway.operations_activity(principal, query)
                status = 200
            elif method == "GET" and path == "/api/v1/notifications":
                response = self.app.gateway.operations_notifications(principal, query)
                status = 200
            elif method == "GET" and path == "/api/v1/agents/status":
                response = self.app.gateway.operations_agent_status(principal, query)
                status = 200
            elif task_events_match:
                response = self.app.gateway.get_task_events(principal, task_events_match.group(1), query)
                status = 200
            elif task_match:
                response = self.app.gateway.get_task(principal, task_match.group(1), query)
                status = 200
            elif method == "GET" and path == "/api/v1/agents":
                response = self.app.gateway.list_agents(principal, query)
                status = 200
            elif agent_match:
                response = self.app.gateway.get_agent(principal, agent_match.group(1), query)
                status = 200
            elif method == "GET" and path == "/api/v1/skills":
                response = self.app.gateway.list_skills(principal, query)
                status = 200
            elif method == "GET" and path == "/api/v1/templates":
                response = self.app.gateway.list_templates()
                status = 200
            elif method == "GET" and path == "/api/v1/marketplace":
                response = self.app.gateway.list_marketplace(query)
                status = 200
            elif method == "GET" and path == "/api/v1/workforce":
                response = self.app.gateway.list_workforce(principal, query)
                status = 200
            elif method == "GET" and path == "/api/v1/workforce/team":
                response = self.app.gateway.workforce_team(principal, query)
                status = 200
            elif method == "POST" and path == "/api/v1/marketplace/publish":
                response = self.app.gateway.publish_marketplace_item(principal, self._body())
                status = 201
            elif marketplace_match and method == "GET" and marketplace_match.group(2) is None:
                response = self.app.gateway.get_marketplace_item(marketplace_match.group(1))
                status = 200
            elif marketplace_match and method == "POST" and marketplace_match.group(2) == "install":
                response = self.app.gateway.install_marketplace_item(principal, marketplace_match.group(1), self._body(), context.request_id)
                status = 202 if response.get("status") == "WAITING_APPROVAL" else 201
            elif workforce_match and method == "GET" and workforce_match.group(2) is None:
                response = self.app.gateway.get_workforce_item(principal, workforce_match.group(1), query)
                status = 200
            elif workforce_match and method == "POST" and workforce_match.group(2):
                response = self.app.gateway.workforce_action(principal, workforce_match.group(1), workforce_match.group(2), self._body())
                status = 201
            elif creator_match and method == "GET":
                response = self.app.gateway.creator_profile(creator_match.group(1))
                status = 200
            elif method == "GET" and path == "/api/v1/creator/packages":
                response = self.app.gateway.creator_packages(principal)
                status = 200
            elif method == "GET" and path == "/api/v1/creator/analytics":
                response = self.app.gateway.creator_analytics(principal)
                status = 200
            elif path in {"/api/v1/agent-definitions", "/api/v1/agent-teams", "/api/v1/agent-plans", "/api/v1/agent-memory", "/api/v1/agent-evaluations"}:
                resource = {"/api/v1/agent-definitions":"agents", "/api/v1/agent-teams":"teams", "/api/v1/agent-plans":"plans", "/api/v1/agent-memory":"memory", "/api/v1/agent-evaluations":"evaluations"}[path]
                response = self.app.gateway.ecosystem_create(principal, resource, self._body()) if method == "POST" else self.app.gateway.ecosystem_list(principal, resource, query)
                status = 201 if method == "POST" else 200
            elif method == "GET" and path == "/api/v1/sdk":
                response = {"language":"python", "mode":"in-process", "arbitrary_code":False, "policy_checked":True}
                status = 200
            elif template_match and method == "GET":
                response = self.app.gateway.get_template(template_match.group(1))
                status = 200
            elif template_match and method == "POST":
                response = self.app.gateway.install_template(principal, template_match.group(1), context.request_id)
                status = 202
            elif method == "GET" and path == "/api/v1/playground/examples":
                response = self.app.gateway.playground_examples()
                status = 200
            elif method == "GET" and path == "/api/v1/organizations":
                response = self.app.gateway.list_organizations(principal)
                status = 200
            elif method == "GET" and path == "/api/v1/workspaces":
                response = self.app.gateway.list_workspaces(principal, query)
                status = 200
            elif method == "POST" and path == "/api/v1/workspaces":
                response = self.app.gateway.create_workspace(principal, self._body())
                status = 201
            elif method == "GET" and path == "/api/v1/members":
                response = self.app.gateway.list_members(principal, query)
                status = 200
            elif method == "POST" and path == "/api/v1/invite":
                response = self.app.gateway.invite_member(principal, self._body())
                status = 201
            elif method == "GET" and path == "/api/v1/knowledge":
                response = self.app.gateway.list_knowledge(principal, query)
                status = 200
            elif method == "POST" and path == "/api/v1/knowledge":
                response = self.app.gateway.add_knowledge(principal, self._body())
                status = 201
            elif method == "GET" and path == "/api/v1/plans":
                response = self.app.gateway.list_plans()
                status = 200
            elif method == "GET" and path == "/api/v1/subscription":
                response = self.app.gateway.get_subscription(principal, query)
                status = 200
            elif method == "GET" and path == "/api/v1/usage":
                response = self.app.gateway.get_usage(principal, query)
                status = 200
            elif method == "GET" and path == "/api/v1/limits":
                response = self.app.gateway.get_limits(principal, query)
                status = 200
            elif method == "POST" and path == "/api/v1/webhooks":
                response = self.app.gateway.request_webhook(principal, self._body(), context.request_id)
                status = 202
            elif method == "GET" and path == "/api/v1/webhooks":
                response = self.app.gateway.list_webhooks(principal)
                status = 200
            elif method == "GET" and path in {"/api/v1/policies", "/api/v1/security/events", "/api/v1/sla", "/api/v1/storage/health"}:
                resource = {"/api/v1/policies": "policies", "/api/v1/security/events": "security_events", "/api/v1/sla": "sla", "/api/v1/storage/health": "storage_health"}[path]
                response = self.app.gateway.enterprise_read(principal, resource, query)
                status = 200
            else:
                raise APIGatewayError(404, "NOT_FOUND", "Ресурс не найден")
            self.app.audit.record("API_SUCCESS", source="public_api", action_result="SUCCESS", request_id=context.request_id, correlation_id=context.correlation_id, endpoint=path, key_id=principal.key_id)
            self.app.metrics.api_request(principal.owner, path, True)
            self._json(status, response, context)
        except APIGatewayError as exc:
            self.app.audit.record("API_DENIED" if exc.status < 500 else "API_ERROR", source="public_api", action_result=exc.code, request_id=context.request_id, correlation_id=context.correlation_id, endpoint=path, key_id=principal.key_id)
            self.app.metrics.api_request(principal.owner, path, False)
            self._json(exc.status, {"error": exc.code, "message": exc.message}, context)
        except ValueError:
            self.app.audit.record("API_DENIED", source="public_api", action_result="VALIDATION_ERROR", request_id=context.request_id, correlation_id=context.correlation_id, endpoint=path, key_id=principal.key_id)
            self.app.metrics.api_request(principal.owner, path, False)
            self._json(400, {"error": "VALIDATION_ERROR"}, context)
        except Exception as exc:
            self.app.audit.record("API_ERROR", severity="ERROR", source="public_api", action_result="INTERNAL_ERROR", request_id=context.request_id, correlation_id=context.correlation_id, endpoint=path, error_type=type(exc).__name__)
            self._json(500, {"error": "INTERNAL_ERROR"}, context)

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid body") from exc
        if length <= 0 or length > MAX_BODY:
            raise ValueError("invalid body")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid body") from exc
        if not isinstance(value, dict):
            raise ValueError("invalid body")
        return value

    def _bearer(self) -> str | None:
        value = self.headers.get("Authorization", "")
        if not value.startswith("Bearer ") or len(value) > 300:
            return None
        return value[7:]

    def _json(self, status: int, value: dict[str, Any], context: Any) -> None:
        body = dict(value)
        body.setdefault("request_id", context.request_id)
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Strict-Transport-Security", "max-age=31536000")
        self.send_header("X-Request-ID", context.request_id)
        self.send_header("X-Correlation-ID", context.correlation_id)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        return


def run(config: PublicAPIConfig | None = None) -> int:
    server = create_server(config or PublicAPIConfig(), use_tls=True)
    print("api=started bind=0.0.0.0:18881 tls=enabled", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
