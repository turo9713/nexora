from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from nexora.dashboard.auth.passwords import hash_password, verify_password


API_SCOPES = {
    "tasks:create",
    "tasks:read",
    "agents:read",
    "skills:read",
    "templates:read",
    "templates:install",
    "playground:read",
    "webhooks:manage",
}
KEY_PATTERN = re.compile(r"^nx_live_([a-f0-9]{12})_([A-Za-z0-9_-]{32,})$")


@dataclass(frozen=True)
class APIKeyPrincipal:
    key_id: str
    owner: str
    name: str
    scopes: frozenset[str]

    def allows(self, scope: str) -> bool:
        return scope in self.scopes


class APIKeyService:
    """Issue opaque one-time keys and persist only a scrypt hash."""

    def __init__(self, database: Any) -> None:
        self.database = database

    def request_key(self, owner: str, name: str, scopes: list[str], expires_at: str | None = None) -> str:
        clean_name = " ".join(str(name).split())[:100]
        normalized = sorted(set(str(scope) for scope in scopes))
        if not clean_name or not normalized or any(scope not in API_SCOPES for scope in normalized):
            raise ValueError("invalid api key request")
        if expires_at is not None:
            expiry = self._timestamp(expires_at)
            if expiry <= datetime.now(timezone.utc):
                raise ValueError("api key expiry must be in the future")
        key_id = f"KEY-{secrets.token_hex(6).upper()}"
        self.database.create_pending_api_key(key_id, owner, clean_name, normalized, expires_at)
        return key_id

    def activate(self, key_id: str, approval_id: str) -> str:
        record = self.database.get_api_key_record(key_id)
        if record is None or record.get("status") != "PENDING" or record.get("approval_id") != approval_id:
            raise KeyError("api key request unavailable")
        public_id = key_id.removeprefix("KEY-").casefold()
        plaintext = f"nx_live_{public_id}_{secrets.token_urlsafe(32)}"
        self.database.activate_api_key(key_id, hash_password(plaintext))
        return plaintext

    def authenticate(self, bearer_value: str, required_scope: str | None = None) -> APIKeyPrincipal | None:
        match = KEY_PATTERN.fullmatch(str(bearer_value or ""))
        if match is None or (required_scope is not None and required_scope not in API_SCOPES):
            return None
        key_id = f"KEY-{match.group(1).upper()}"
        record = self.database.get_api_key_record(key_id)
        if record is None or record.get("status") != "ACTIVE":
            return None
        expires_at = record.get("expires_at")
        if expires_at and self._timestamp(str(expires_at)) <= datetime.now(timezone.utc):
            return None
        if not verify_password(bearer_value, str(record.get("key_hash") or "")):
            return None
        try:
            scopes = frozenset(json.loads(str(record.get("scopes") or "[]")))
        except (TypeError, json.JSONDecodeError):
            return None
        if (required_scope is not None and required_scope not in scopes) or not scopes.issubset(API_SCOPES):
            return None
        self.database.touch_api_key(key_id)
        return APIKeyPrincipal(key_id, str(record["owner"]), str(record["name"]), scopes)

    def disable(self, owner: str, key_id: str, approval_id: str) -> None:
        self._require_approval(owner, key_id, approval_id)
        self.database.set_api_key_status(owner, key_id, "DISABLED")

    def delete(self, owner: str, key_id: str, approval_id: str) -> None:
        self._require_approval(owner, key_id, approval_id)
        self.database.set_api_key_status(owner, key_id, "DELETED")

    def list(self, owner: str) -> list[dict[str, Any]]:
        result = []
        for item in self.database.list_api_keys(owner):
            safe = dict(item)
            safe["scopes"] = json.loads(str(item.get("scopes") or "[]"))
            result.append(safe)
        return result

    def _require_approval(self, owner: str, key_id: str, approval_id: str) -> None:
        record = self.database.get_api_key_record(key_id)
        if record is None or record.get("owner") != owner or record.get("approval_id") != approval_id:
            raise PermissionError("api key approval required")

    @staticmethod
    def _timestamp(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed.astimezone(timezone.utc)
