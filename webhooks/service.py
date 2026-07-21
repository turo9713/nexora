from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import ssl
import time
import urllib.request
from typing import Any, Callable
from urllib.parse import urlsplit

from nexora.security.audit.redaction import sanitize_metadata


WEBHOOK_EVENTS = {"TASK_CREATED", "TASK_COMPLETED", "TASK_FAILED", "APPROVAL_REQUIRED", "SECURITY_EVENT"}


class WebhookValidationError(ValueError):
    pass


def verify_signature(secret: str, payload: bytes, signature: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(signature))


class WebhookService:
    def __init__(
        self,
        database: Any,
        master_key: bytes,
        *,
        audit: Any | None = None,
        transport: Callable[[str, bytes, dict[str, str], float], int] | None = None,
        resolver: Callable[..., Any] = socket.getaddrinfo,
        sleeper: Callable[[float], None] = time.sleep,
        timeout_seconds: float = 5.0,
        max_attempts: int = 3,
        disable_after: int = 5,
    ) -> None:
        if len(master_key) < 32:
            raise ValueError("webhook master key is too short")
        self.database = database
        self.master_key = master_key
        self.audit = audit
        self.transport = transport or self._http_transport
        self.resolver = resolver
        self.sleeper = sleeper
        self.timeout_seconds = min(10.0, max(1.0, float(timeout_seconds)))
        self.max_attempts = min(5, max(1, int(max_attempts)))
        self.disable_after = min(20, max(2, int(disable_after)))

    def request_webhook(self, owner: str, url: str, events: list[str]) -> str:
        self._validate_url(url, resolve=False)
        normalized = sorted(set(events))
        if not normalized or any(event not in WEBHOOK_EVENTS for event in normalized):
            raise WebhookValidationError("invalid webhook events")
        webhook_id = f"WH-{secrets.token_hex(6).upper()}"
        self.database.create_pending_webhook(webhook_id, owner, url, normalized)
        return webhook_id

    def activate(self, webhook_id: str, approval_id: str) -> str:
        record = self.database.get_webhook_record(webhook_id)
        if record is None or record.get("status") != "PENDING" or record.get("approval_id") != approval_id:
            raise KeyError("webhook request unavailable")
        secret = self._secret(webhook_id)
        self.database.activate_webhook(webhook_id, hashlib.sha256(secret.encode("utf-8")).hexdigest())
        return secret

    def disable(self, owner: str, webhook_id: str, approval_id: str) -> None:
        self._require_approval(owner, webhook_id, approval_id)
        self.database.set_webhook_status(owner, webhook_id, "DISABLED")

    def delete(self, owner: str, webhook_id: str, approval_id: str) -> None:
        self._require_approval(owner, webhook_id, approval_id)
        self.database.set_webhook_status(owner, webhook_id, "DELETED")

    def list(self, owner: str) -> list[dict[str, Any]]:
        values = []
        for item in self.database.list_webhooks(owner):
            safe = dict(item)
            safe["events"] = json.loads(str(item.get("events") or "[]"))
            values.append(safe)
        return values

    def dispatch(self, owner: str, event: str, payload: dict[str, Any], request_id: str) -> list[dict[str, Any]]:
        if event not in WEBHOOK_EVENTS:
            raise WebhookValidationError("unsupported webhook event")
        envelope = {
            "event": event,
            "request_id": str(request_id)[:100],
            "data": sanitize_metadata(payload),
        }
        body = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        outcomes = []
        for item in self.database.list_webhooks(owner, active_only=True):
            events = json.loads(str(item.get("events") or "[]"))
            if event not in events:
                continue
            outcomes.append(self._deliver(item, event, body, request_id))
        return outcomes

    def _deliver(self, item: dict[str, Any], event: str, body: bytes, request_id: str) -> dict[str, Any]:
        webhook_id = str(item["id"])
        url = str(item["url"])
        self._validate_url(url, resolve=True)
        secret = self._secret(webhook_id)
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Nexora-Webhooks/1.8",
            "X-Nexora-Event": event,
            "X-Nexora-Request-ID": request_id,
            "X-Nexora-Signature": "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest(),
        }
        success = False
        attempts = 0
        for attempt in range(1, self.max_attempts + 1):
            attempts = attempt
            delivery_id = f"WHD-{secrets.token_hex(8).upper()}"
            try:
                status = int(self.transport(url, body, headers, self.timeout_seconds))
                success = 200 <= status < 300
            except Exception:
                success = False
            self.database.insert_webhook_delivery({
                "id": delivery_id,
                "webhook_id": webhook_id,
                "event": event,
                "request_id": request_id,
                "attempt": attempt,
                "status": "SUCCEEDED" if success else "FAILED",
            })
            if success:
                break
            if attempt < self.max_attempts:
                self.sleeper(float((attempt - 1) ** 2))
        self.database.record_webhook_result(webhook_id, success=success, disable_after=self.disable_after)
        if self.audit is not None:
            self.audit.record(
                "WEBHOOK_DELIVERY",
                source="webhook_service",
                action_result="SUCCEEDED" if success else "FAILED",
                webhook_id=webhook_id,
                event_type=event,
                request_id=request_id,
                attempts=attempts,
            )
        return {"webhook_id": webhook_id, "status": "SUCCEEDED" if success else "FAILED", "attempts": attempts}

    def _secret(self, webhook_id: str) -> str:
        digest = hmac.new(self.master_key, f"webhook:{webhook_id}".encode("ascii"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def _require_approval(self, owner: str, webhook_id: str, approval_id: str) -> None:
        record = self.database.get_webhook_record(webhook_id)
        if record is None or record.get("owner") != owner or record.get("approval_id") != approval_id:
            raise PermissionError("webhook approval required")

    def _validate_url(self, url: str, *, resolve: bool) -> None:
        parsed = urlsplit(str(url))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise WebhookValidationError("webhook URL must be a plain HTTPS endpoint")
        if parsed.port not in {None, 443}:
            raise WebhookValidationError("webhook port is not allowed")
        if resolve:
            try:
                addresses = self.resolver(parsed.hostname, 443, type=socket.SOCK_STREAM)
            except OSError as exc:
                raise WebhookValidationError("webhook host cannot be resolved") from exc
            for address in addresses:
                ip = ipaddress.ip_address(address[4][0])
                if not ip.is_global:
                    raise WebhookValidationError("webhook target is not public")

    @staticmethod
    def _http_transport(url: str, body: bytes, headers: dict[str, str], timeout: float) -> int:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        context = ssl.create_default_context()
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return int(response.status)
