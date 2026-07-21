from __future__ import annotations

import json
import mimetypes
import os
import re
import ssl
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from nexora.agents.registry import AgentRegistry
from nexora.dashboard.api import DashboardAPI, DashboardAPIError
from nexora.dashboard.auth import AuthService, BruteForceProtector, Session, SessionManager
from nexora.dashboard.permissions import DashboardPermissions
from nexora.collaboration import TeamService
from nexora.billing import BillingFoundation
from nexora.admin import AdminConsole
from nexora.database import SQLiteRepository
from nexora.integrations.telegram_runtime.services.approval_service import ApprovalService
from nexora.integrations.telegram_runtime.services.audit_service import AuditService
from nexora.integrations.telegram_runtime.services.task_service import TaskService
from nexora.integrations.telegram_runtime.storage.approval_repository import ApprovalRepository
from nexora.integrations.telegram_runtime.storage.audit_repository import AuditRepository
from nexora.integrations.telegram_runtime.storage.task_repository import TaskRepository
from nexora.runtime.events import EventBus, SQLiteEventSink
from nexora.security.policies import PolicyEngine
from nexora.skills import SkillRegistry
from nexora.api.auth import APIKeyService
from nexora.metrics import MetricsService
from nexora.playground import PlaygroundService
from nexora.templates import TemplateRegistry
from nexora.webhooks import WebhookService
from nexora.marketplace import MarketplaceService
from nexora.creators import CreatorService


COOKIE_NAME = "__Host-nexora_session"
MAX_BODY = 64 * 1024
TASK_ID = re.compile(r"^[A-Za-z0-9-]{3,100}$")
AGENT_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
APPROVAL_ID = re.compile(r"^APR-[A-Z0-9]{8}$")
SKILL_ID = re.compile(r"^[a-z][a-z0-9-]{1,63}$")


@dataclass(frozen=True)
class DashboardConfig:
    host: str = "0.0.0.0"
    port: int = 18880
    project_root: Path = Path("/workspace/nexora")
    state_root: Path = Path("/workspace/nexora/runtime/state/telegram_v14")
    database_path: Path = Path("/workspace/nexora/runtime/state/database/nexora.sqlite3")
    password_hash_file: Path = Path("/run/secrets/dashboard_password_hash")
    session_key_file: Path = Path("/run/secrets/dashboard_session_key")
    owner_namespace_file: Path = Path("/run/secrets/dashboard_owner_namespace")
    tls_cert_file: Path | None = Path("/run/secrets/dashboard_tls_cert")
    tls_key_file: Path | None = Path("/run/secrets/dashboard_tls_key")
    webhook_master_file: Path = Path("/run/secrets/api_webhook_master")
    allowed_origins: tuple[str, ...] = ("https://127.0.0.1:18880", "https://localhost:18880")
    session_ttl_seconds: int = 1800


class RequestRateLimiter:
    def __init__(self, limit: int = 300, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            values = [value for value in self._requests.get(key, []) if value >= cutoff]
            if len(values) >= self.limit:
                self._requests[key] = values
                return False
            values.append(now)
            self._requests[key] = values
            return True


@dataclass
class DashboardApplication:
    config: DashboardConfig
    api: DashboardAPI
    auth: AuthService
    sessions: SessionManager
    permissions: DashboardPermissions
    limiter: RequestRateLimiter


def _read_secret(path: Path, minimum: int = 1) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("dashboard secret is unavailable")
    value = path.read_bytes().strip()
    if len(value) < minimum:
        raise RuntimeError("dashboard secret is invalid")
    return value


def create_application(config: DashboardConfig) -> DashboardApplication:
    password_hash = _read_secret(config.password_hash_file, 40).decode("ascii")
    session_key = _read_secret(config.session_key_file, 32)
    namespace = _read_secret(config.owner_namespace_file, 32).decode("ascii")
    if not re.fullmatch(r"[a-f0-9]{32,64}", namespace):
        raise RuntimeError("dashboard owner namespace is invalid")

    database = SQLiteRepository(config.database_path)
    database.migrate()
    database.import_task_directory(config.state_root / "tasks")
    registry = AgentRegistry(config.project_root / "agents").load()
    policy = PolicyEngine(registry, config.project_root, status_resolver=database.agent_enabled)
    events = EventBus([SQLiteEventSink(database)])
    tasks = TaskService(TaskRepository(config.state_root / "tasks"), database=database, event_bus=events)
    approvals = ApprovalService(
        ApprovalRepository(config.state_root / "approvals"),
        database=database,
        event_bus=events,
    )
    audit = AuditService(AuditRepository(config.state_root / "audit"), database=database)
    sessions = SessionManager(session_key, ttl_seconds=config.session_ttl_seconds, audit=audit.record)
    auth = AuthService(password_hash, sessions, BruteForceProtector(), audit.record)
    skills = SkillRegistry(
        config.project_root / "skills" / "manifests",
        database=database,
        audit=audit,
        agent_registry=registry,
    ).load()
    api_keys = APIKeyService(database)
    webhooks = WebhookService(database, _read_secret(config.webhook_master_file, 32), audit=audit)
    metrics = MetricsService(database)
    templates = TemplateRegistry(config.project_root / "templates", database=database, agents=registry, skills=skills, policy=policy, audit=audit, metrics=metrics).load()
    playground = PlaygroundService(audit)
    teams = TeamService(database, policy, audit)
    teams.bootstrap_personal(namespace)
    billing = BillingFoundation(database, audit)
    admin_console = AdminConsole(billing, namespace, policy)
    marketplace = MarketplaceService(database, teams, policy, audit)
    creators = CreatorService(database, marketplace, teams, policy, audit, administrator=namespace)
    api = DashboardAPI(database, registry, policy, tasks, approvals, audit, skills, api_keys, webhooks, metrics, namespace, templates=templates, playground=playground, teams=teams, billing=billing, admin_console=admin_console, marketplace=marketplace, creators=creators)
    return DashboardApplication(config, api, auth, sessions, DashboardPermissions(), RequestRateLimiter())


def create_server(config: DashboardConfig, *, use_tls: bool = True) -> ThreadingHTTPServer:
    application = create_application(config)

    class Handler(DashboardRequestHandler):
        app = application

    server = ThreadingHTTPServer((config.host, config.port), Handler)
    server.daemon_threads = True
    if use_tls:
        if config.tls_cert_file is None or config.tls_key_file is None:
            raise RuntimeError("TLS configuration is required")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(config.tls_cert_file, config.tls_key_file)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


class DashboardRequestHandler(BaseHTTPRequestHandler):
    app: DashboardApplication
    server_version = "NexoraDashboard/2.5"
    sys_version = ""

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/healthz":
            self._json(200, {"status": "ok"})
            return
        if path.startswith("/api/"):
            if not self.app.limiter.allow(self.client_address[0]):
                self.app.api.audit_access(path, "RATE_LIMITED")
                self._json(429, {"error": "RATE_LIMITED"})
                return
            self._handle_api_get(path, dict(parse_qsl(parsed.query, keep_blank_values=True)))
            return
        self._serve_frontend(path)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if not self.app.limiter.allow(self.client_address[0]):
            self.app.api.audit_access(path, "RATE_LIMITED")
            self._json(429, {"error": "RATE_LIMITED"})
            return
        if path == "/api/login":
            self._login()
            return
        session = self._require_session(self._permission_for(path, "POST"))
        if session is None:
            return
        if not self._valid_origin() or self.headers.get("X-CSRF-Token", "") != session.csrf_token:
            self.app.api.audit_access(path, "CSRF_DENIED")
            self._json(403, {"error": "CSRF_DENIED"})
            return
        if path == "/api/logout":
            self.app.auth.logout(self._cookie_value())
            self._json(200, {"status": "LOGGED_OUT"}, clear_cookie=True)
            return
        body = self._json_body()
        if body is None:
            return
        try:
            agent_match = re.fullmatch(r"/api/agents/([^/]+)/actions", path)
            skill_match = re.fullmatch(r"/api/skills/([^/]+)/(enable|disable|reload)", path)
            template_install_match = re.fullmatch(r"/api/templates/([^/]+)/install", path)
            key_action_match = re.fullmatch(r"/api/platform/api-keys/(KEY-[A-F0-9]{12})/(disable|delete)", path)
            webhook_action_match = re.fullmatch(r"/api/platform/webhooks/(WH-[A-F0-9]{12})/(disable|delete)", path)
            plan_change_match = re.fullmatch(r"/api/admin/organizations/(ORG-[A-F0-9]{12})/plan", path)
            organization_status_match = re.fullmatch(r"/api/admin/organizations/(ORG-[A-F0-9]{12})/(block|unblock)", path)
            marketplace_install_match = re.fullmatch(r"/api/marketplace/([a-z0-9][a-z0-9-]{1,62})/install", path)
            creator_action_match = re.fullmatch(r"/api/creator/packages/([a-z0-9][a-z0-9-]{1,62})/([0-9]+\.[0-9]+\.[0-9]+)/(submit|validate|publish)", path)
            approval_match = re.fullmatch(r"/api/approvals/([^/]+)/(approve|reject)", path)
            if agent_match:
                agent_id = agent_match.group(1)
                if not AGENT_ID.fullmatch(agent_id):
                    raise DashboardAPIError(404, "AGENT_NOT_FOUND", "Агент не найден")
                response = self.app.api.request_agent_action(agent_id, str(body.get("action") or ""), session.session_id)
                self.app.api.audit_access(path)
                self._json(202, response)
                return
            if path == "/api/platform/api-keys":
                response = self.app.api.request_api_key_create(body, session.session_id)
                self.app.api.audit_access(path)
                self._json(202, response)
                return
            if key_action_match:
                key_id, action = key_action_match.groups()
                response = self.app.api.request_api_key_action(key_id, action, session.session_id)
                self.app.api.audit_access(path)
                self._json(202, response)
                return
            if path == "/api/platform/webhooks":
                response = self.app.api.request_webhook_create(body, session.session_id)
                self.app.api.audit_access(path)
                self._json(202, response)
                return
            if webhook_action_match:
                webhook_id, action = webhook_action_match.groups()
                response = self.app.api.request_webhook_action(webhook_id, action, session.session_id)
                self.app.api.audit_access(path)
                self._json(202, response)
                return
            if plan_change_match:
                response = self.app.api.request_plan_change(plan_change_match.group(1), str(body.get("plan_id") or ""), session.session_id)
                self.app.api.audit_access(path)
                self._json(202, response)
                return
            if organization_status_match:
                organization_id, action = organization_status_match.groups()
                response = self.app.api.request_organization_block(organization_id, action == "block", session.session_id)
                self.app.api.audit_access(path)
                self._json(202, response)
                return
            if skill_match:
                skill_id, action = skill_match.groups()
                if not SKILL_ID.fullmatch(skill_id):
                    raise DashboardAPIError(404, "SKILL_NOT_FOUND", "Skill не найден")
                response = self.app.api.request_skill_action(skill_id, action, session.session_id)
                self.app.api.audit_access(path)
                self._json(202, response)
                return
            if template_install_match:
                template_id = template_install_match.group(1)
                if not AGENT_ID.fullmatch(template_id):
                    raise DashboardAPIError(404, "TEMPLATE_NOT_FOUND", "Template not found")
                response = self.app.api.request_template_install(template_id, session.session_id)
                self.app.api.audit_access(path)
                self._json(202, response)
                return
            if approval_match:
                approval_id, decision = approval_match.groups()
                if not APPROVAL_ID.fullmatch(approval_id):
                    raise DashboardAPIError(404, "APPROVAL_NOT_FOUND", "Подтверждение не найдено")
                response = self.app.api.decide_approval(approval_id, decision)
                self.app.api.audit_access(path)
                self._json(200, response)
                return
            if path == "/api/publisher/register":
                response = self.app.api.register_publisher(body, session.session_id)
                self.app.api.audit_access(path)
                self._json(202, response)
                return
            if path == "/api/marketplace/publish":
                response = self.app.api.publish_marketplace(body)
                self.app.api.audit_access(path)
                self._json(201, response)
                return
            if path == "/api/creator/profile":
                response = self.app.api.create_creator_profile(body)
                self.app.api.audit_access(path)
                self._json(201, response)
                return
            if path == "/api/creator/packages":
                response = self.app.api.create_creator_draft(body)
                self.app.api.audit_access(path)
                self._json(201, response)
                return
            if creator_action_match:
                package_id, version, action = creator_action_match.groups()
                response = self.app.api.creator_version_action(package_id, version, action)
                self.app.api.audit_access(path)
                self._json(200, response)
                return
            if marketplace_install_match:
                response = self.app.api.request_marketplace_install(marketplace_install_match.group(1), body, session.session_id)
                self.app.api.audit_access(path)
                self._json(202 if response.get("status") == "WAITING_APPROVAL" else 201, response)
                return
            self._json(404, {"error": "NOT_FOUND"})
        except DashboardAPIError as exc:
            self.app.api.audit_access(path, exc.code)
            self._json(exc.status, {"error": exc.code, "message": exc.message})

    def _handle_api_get(self, path: str, query: dict[str, str]) -> None:
        permission = self._permission_for(path, "GET")
        session = self._require_session(permission)
        if session is None:
            return
        try:
            if path == "/api/session":
                response: Any = {"authenticated": True, "csrf_token": session.csrf_token, "expires_at": session.expires_at}
            elif path == "/api/health":
                response = self.app.api.health()
            elif path == "/api/tasks":
                response = self.app.api.list_tasks(query)
            elif path == "/api/agents":
                response = self.app.api.list_agents()
            elif path == "/api/skills":
                response = self.app.api.list_skills()
            elif path == "/api/templates":
                response = self.app.api.list_templates()
            elif path == "/api/playground/examples":
                response = self.app.api.playground_examples()
            elif path == "/api/organizations":
                response = self.app.api.list_organizations()
            elif path == "/api/workspaces":
                response = self.app.api.list_workspaces(query)
            elif path == "/api/members":
                response = self.app.api.list_members(query)
            elif path == "/api/knowledge":
                response = self.app.api.list_knowledge(query)
            elif path == "/api/plans":
                response = self.app.api.list_plans()
            elif path == "/api/billing":
                response = self.app.api.billing_summary(query)
            elif path == "/api/usage-v23":
                response = self.app.api.usage_summary_v23(query)
            elif path == "/api/limits":
                response = self.app.api.limits_summary(query)
            elif path == "/api/admin":
                response = self.app.api.admin_summary()
            elif path == "/api/marketplace":
                response = self.app.api.marketplace_catalog(query)
            elif path == "/api/my-items":
                response = self.app.api.marketplace_my_items()
            elif path == "/api/publisher":
                response = self.app.api.marketplace_my_items()
            elif path == "/api/creator":
                response = self.app.api.creator_dashboard()
            elif path == "/api/approvals":
                response = self.app.api.list_approvals(query)
            elif path == "/api/audit":
                response = self.app.api.audit_events(query)
            elif path == "/api/platform/api-keys":
                response = self.app.api.list_api_keys()
            elif path == "/api/platform/webhooks":
                response = self.app.api.list_webhooks()
            elif path == "/api/platform/metrics":
                response = self.app.api.metrics_summary()
            elif path == "/api/platform/integrations":
                response = self.app.api.integrations()
            else:
                task_match = re.fullmatch(r"/api/tasks/([^/]+)", path)
                agent_match = re.fullmatch(r"/api/agents/([^/]+)", path)
                skill_match = re.fullmatch(r"/api/skills/([^/]+)", path)
                template_match = re.fullmatch(r"/api/templates/([^/]+)", path)
                marketplace_match = re.fullmatch(r"/api/marketplace/([a-z0-9][a-z0-9-]{1,62})", path)
                if task_match and TASK_ID.fullmatch(task_match.group(1)):
                    response = self.app.api.task_details(task_match.group(1))
                elif agent_match and AGENT_ID.fullmatch(agent_match.group(1)):
                    response = self.app.api.agent_details(agent_match.group(1))
                elif skill_match and SKILL_ID.fullmatch(skill_match.group(1)):
                    response = self.app.api.skill_details(skill_match.group(1))
                elif template_match and AGENT_ID.fullmatch(template_match.group(1)):
                    response = self.app.api.template_details(template_match.group(1))
                elif marketplace_match:
                    response = self.app.api.marketplace_item(marketplace_match.group(1))
                else:
                    raise DashboardAPIError(404, "NOT_FOUND", "Ресурс не найден")
            self.app.api.audit_access(path)
            self._json(200, response)
        except DashboardAPIError as exc:
            self.app.api.audit_access(path, exc.code)
            self._json(exc.status, {"error": exc.code, "message": exc.message})

    def _login(self) -> None:
        if not self._valid_origin():
            self.app.api.audit.record("LOGIN_FAILED", severity="SECURITY", source="dashboard_auth", action_result="ORIGIN_DENIED")
            self._json(403, {"error": "ORIGIN_DENIED"})
            return
        body = self._json_body()
        if body is None:
            return
        username = str(body.get("username") or "")[:64]
        password = str(body.get("password") or "")[:256]
        result = self.app.auth.login(username, password, self.client_address[0])
        if not result.ok or result.session is None or result.cookie is None:
            status = 429 if result.code == "AUTH_RATE_LIMITED" else 401
            self._json(status, {"error": result.code})
            return
        self._json(
            200,
            {"authenticated": True, "csrf_token": result.session.csrf_token, "expires_at": result.session.expires_at},
            cookie=result.cookie,
        )

    def _require_session(self, permission: str | None) -> Session | None:
        session = self.app.sessions.validate(self._cookie_value())
        if permission is None or not self.app.permissions.authorize(session, permission):
            self.app.api.audit_access(urlsplit(self.path).path, "UNAUTHORIZED" if session is None else "FORBIDDEN")
            self._json(401 if session is None else 403, {"error": "UNAUTHORIZED" if session is None else "FORBIDDEN"})
            return None
        return session

    def _permission_for(self, path: str, method: str) -> str | None:
        if method == "GET":
            if path in {"/api/session", "/api/health"}:
                return "health:read"
            if path == "/api/tasks" or path.startswith("/api/tasks/"):
                return "tasks:read"
            if path == "/api/agents" or path.startswith("/api/agents/"):
                return "agents:read"
            if path == "/api/skills" or path.startswith("/api/skills/"):
                return "skills:read"
            if path == "/api/templates" or path.startswith("/api/templates/"):
                return "templates:read"
            if path == "/api/playground/examples":
                return "playground:read"
            if path == "/api/organizations":
                return "organizations:read"
            if path == "/api/workspaces":
                return "workspaces:read"
            if path == "/api/members":
                return "members:read"
            if path == "/api/knowledge":
                return "knowledge:read"
            if path == "/api/plans":
                return "plans:read"
            if path == "/api/billing":
                return "billing:read"
            if path == "/api/usage-v23":
                return "usage:read"
            if path == "/api/limits":
                return "limits:read"
            if path == "/api/admin":
                return "admin:read"
            if path == "/api/marketplace" or path.startswith("/api/marketplace/"):
                return "marketplace:read"
            if path in {"/api/my-items", "/api/publisher"}:
                return "marketplace:read"
            if path == "/api/creator":
                return "creator:read"
            if path == "/api/approvals":
                return "approvals:read"
            if path == "/api/audit":
                return "audit:read"
            if path.startswith("/api/platform/api-keys"):
                return "api_keys:read"
            if path.startswith("/api/platform/webhooks"):
                return "webhooks:read"
            if path == "/api/platform/metrics":
                return "metrics:read"
            if path == "/api/platform/integrations":
                return "integrations:read"
        if method == "POST":
            if path == "/api/logout":
                return "health:read"
            if re.fullmatch(r"/api/agents/[^/]+/actions", path):
                return "agents:request_change"
            if re.fullmatch(r"/api/skills/[^/]+/(enable|disable|reload)", path):
                return "skills:request_change"
            if re.fullmatch(r"/api/templates/[^/]+/install", path):
                return "templates:install"
            if re.fullmatch(r"/api/approvals/[^/]+/(approve|reject)", path):
                return "approvals:decide"
            if path == "/api/platform/api-keys" or re.fullmatch(r"/api/platform/api-keys/KEY-[A-F0-9]{12}/(disable|delete)", path):
                return "api_keys:manage"
            if path == "/api/platform/webhooks" or re.fullmatch(r"/api/platform/webhooks/WH-[A-F0-9]{12}/(disable|delete)", path):
                return "webhooks:manage"
            if re.fullmatch(r"/api/admin/organizations/ORG-[A-F0-9]{12}/(?:plan|block|unblock)", path):
                return "admin:manage"
            if path in {"/api/publisher/register", "/api/marketplace/publish"} or re.fullmatch(r"/api/marketplace/[a-z0-9][a-z0-9-]{1,62}/install", path):
                return "marketplace:manage"
            if path in {"/api/creator/profile", "/api/creator/packages"} or re.fullmatch(r"/api/creator/packages/[a-z0-9][a-z0-9-]{1,62}/[0-9]+\.[0-9]+\.[0-9]+/(submit|validate|publish)", path):
                return "creator:manage"
        return None

    def _json_body(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._json(400, {"error": "INVALID_BODY"})
            return None
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            self._json(400, {"error": "INVALID_JSON"})
            return None
        if not isinstance(value, dict):
            self._json(400, {"error": "INVALID_BODY"})
            return None
        return value

    def _cookie_value(self) -> str | None:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        morsel = cookie.get(COOKIE_NAME)
        return morsel.value if morsel is not None else None

    def _valid_origin(self) -> bool:
        return self.headers.get("Origin", "") in self.app.config.allowed_origins

    def _serve_frontend(self, path: str) -> None:
        frontend = self.app.config.project_root / "dashboard" / "frontend"
        asset = path.removeprefix("/assets/") if path.startswith("/assets/") else ""
        if asset and re.fullmatch(r"[A-Za-z0-9_.-]+", asset):
            target = frontend / asset
        elif path == "/" or path.startswith(("/tasks", "/agents", "/skills", "/templates", "/playground", "/organizations", "/workspaces", "/members", "/knowledge", "/billing", "/usage", "/plans", "/admin", "/marketplace", "/my-items", "/publisher", "/creator", "/approvals", "/audit", "/api-keys", "/webhooks", "/metrics", "/integrations")):
            target = frontend / "index.html"
        else:
            self._json(404, {"error": "NOT_FOUND"})
            return
        if not target.is_file() or target.is_symlink():
            self._json(404, {"error": "NOT_FOUND"})
            return
        content = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self._security_headers()
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store" if target.name == "index.html" else "private, max-age=300")
        self.end_headers()
        self.wfile.write(content)

    def _json(
        self,
        status: int,
        value: dict[str, Any],
        *,
        cookie: str | None = None,
        clear_cookie: bool = False,
    ) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        if cookie is not None:
            self.send_header("Set-Cookie", f"{COOKIE_NAME}={cookie}; Path=/; Secure; HttpOnly; SameSite=Strict")
        elif clear_cookie:
            self.send_header("Set-Cookie", f"{COOKIE_NAME}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict")
        self.end_headers()
        self.wfile.write(payload)

    def _security_headers(self) -> None:
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header("Strict-Transport-Security", "max-age=31536000")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")

    def log_message(self, format: str, *args: Any) -> None:
        return


def run(config: DashboardConfig | None = None) -> int:
    config = config or DashboardConfig()
    server = create_server(config, use_tls=True)
    print(f"dashboard=started bind={config.host}:{config.port} tls=enabled", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
