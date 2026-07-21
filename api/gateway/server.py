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
from nexora.api.auth import APIKeyService
from nexora.api.gateway.service import APIGateway, APIGatewayError
from nexora.api.middleware import request_context
from nexora.api.rate_limit import APIRateLimiter
from nexora.database import SQLiteRepository
from nexora.integrations.telegram_runtime.services.approval_service import ApprovalService
from nexora.integrations.telegram_runtime.services.audit_service import AuditService
from nexora.integrations.telegram_runtime.services.task_service import TaskService
from nexora.integrations.telegram_runtime.storage.approval_repository import ApprovalRepository
from nexora.integrations.telegram_runtime.storage.audit_repository import AuditRepository
from nexora.integrations.telegram_runtime.storage.task_repository import TaskRepository
from nexora.metrics import MetricsService
from nexora.runtime.events import EventBus, SQLiteEventSink
from nexora.security.policies import PolicyEngine
from nexora.skills import SkillRegistry
from nexora.webhooks import WebhookService


MAX_BODY = 32 * 1024
TASK_ID = re.compile(r"^[A-Za-z0-9-]{3,100}$")
ROUTES = {
    ("POST", "/api/v1/tasks"): ("tasks:create", 10),
    ("GET", "/api/v1/tasks"): ("tasks:read", 60),
    ("GET", "/api/v1/agents"): ("agents:read", 60),
    ("GET", "/api/v1/skills"): ("skills:read", 60),
    ("POST", "/api/v1/webhooks"): ("webhooks:manage", 10),
    ("GET", "/api/v1/webhooks"): ("webhooks:manage", 30),
}


@dataclass(frozen=True)
class PublicAPIConfig:
    host: str = "0.0.0.0"
    port: int = 18881
    project_root: Path = Path("/workspace/nexora")
    state_root: Path = Path("/workspace/nexora/runtime/state/telegram_v14")
    database_path: Path = Path("/workspace/nexora/runtime/state/database/nexora.sqlite3")
    webhook_master_file: Path = Path("/run/secrets/api_webhook_master")
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
        platform_version="1.8.0",
    ).load()
    events = EventBus([SQLiteEventSink(database)])
    tasks = TaskService(TaskRepository(config.state_root / "tasks"), database=database, event_bus=events)
    approvals = ApprovalService(ApprovalRepository(config.state_root / "approvals"), database=database, event_bus=events)
    webhooks = WebhookService(database, _secret(config.webhook_master_file), audit=audit)
    metrics = MetricsService(database)
    gateway = APIGateway(database, agents, skills, policy, tasks, approvals, webhooks, metrics)
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
    server_version = "NexoraAPI/1.8"
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
        task_match = re.fullmatch(r"/api/v1/tasks/([^/]+)", path) if method == "GET" else None
        if route is None and task_match and TASK_ID.fullmatch(task_match.group(1)):
            route = ("tasks:read", 60)
        if route is None:
            if path.startswith("/api/"):
                self.app.audit.record("API_DENIED", severity="SECURITY", source="public_api", action_result="NOT_FOUND", request_id=context.request_id, method=method, endpoint=path)
            self._json(404, {"error": "NOT_FOUND"}, context)
            return
        scope, limit = route
        self.app.audit.record("API_REQUEST", source="public_api", action_result="RECEIVED", request_id=context.request_id, method=method, endpoint=path)
        bearer = self._bearer()
        principal = self.app.keys.authenticate(bearer) if bearer else None
        if principal is None:
            self.app.audit.record("API_DENIED", severity="SECURITY", source="public_api", action_result="DENIED", request_id=context.request_id, endpoint=path, reason="authentication_or_scope")
            self.app.metrics.api_request(None, path, False)
            self._json(401, {"error": "UNAUTHORIZED"}, context)
            return
        if not principal.allows(scope):
            self.app.audit.record("API_DENIED", severity="SECURITY", source="public_api", action_result="SCOPE_DENIED", request_id=context.request_id, endpoint=path, key_id=principal.key_id)
            self.app.metrics.api_request(principal.owner, path, False)
            self._json(403, {"error": "SCOPE_DENIED"}, context)
            return
        if not self.app.rate_limiter.allow(principal.key_id, principal.owner, path, limit=limit):
            self.app.audit.record("API_RATE_LIMITED", source="public_api", action_result="RATE_LIMITED", request_id=context.request_id, endpoint=path, key_id=principal.key_id)
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
            elif task_match:
                response = self.app.gateway.get_task(principal, task_match.group(1))
                status = 200
            elif method == "GET" and path == "/api/v1/agents":
                response = self.app.gateway.list_agents()
                status = 200
            elif method == "GET" and path == "/api/v1/skills":
                response = self.app.gateway.list_skills()
                status = 200
            elif method == "POST" and path == "/api/v1/webhooks":
                response = self.app.gateway.request_webhook(principal, self._body(), context.request_id)
                status = 202
            elif method == "GET" and path == "/api/v1/webhooks":
                response = self.app.gateway.list_webhooks(principal)
                status = 200
            else:
                raise APIGatewayError(404, "NOT_FOUND", "Ресурс не найден")
            self.app.audit.record("API_SUCCESS", source="public_api", action_result="SUCCESS", request_id=context.request_id, endpoint=path, key_id=principal.key_id)
            self.app.metrics.api_request(principal.owner, path, True)
            self._json(status, response, context)
        except APIGatewayError as exc:
            self.app.audit.record("API_DENIED" if exc.status < 500 else "API_ERROR", source="public_api", action_result=exc.code, request_id=context.request_id, endpoint=path, key_id=principal.key_id)
            self.app.metrics.api_request(principal.owner, path, False)
            self._json(exc.status, {"error": exc.code, "message": exc.message}, context)
        except ValueError:
            self.app.audit.record("API_DENIED", source="public_api", action_result="VALIDATION_ERROR", request_id=context.request_id, endpoint=path, key_id=principal.key_id)
            self.app.metrics.api_request(principal.owner, path, False)
            self._json(400, {"error": "VALIDATION_ERROR"}, context)
        except Exception as exc:
            self.app.audit.record("API_ERROR", severity="ERROR", source="public_api", action_result="INTERNAL_ERROR", request_id=context.request_id, endpoint=path, error_type=type(exc).__name__)
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
