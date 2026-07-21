from __future__ import annotations

import hashlib
import hmac
from typing import Any


class AccessControl:
    def __init__(self, owner_id: int, namespace_key: bytes) -> None:
        if not namespace_key:
            raise ValueError("namespace key is required")
        self.owner_id = owner_id
        self._namespace_key = namespace_key
        self.owner_namespace = self._namespace("owner", str(owner_id))
        self.security_namespace = self._namespace("security", "denied-events")

    def _namespace(self, purpose: str, value: str) -> str:
        payload = f"nexora:{purpose}:{value}".encode("utf-8")
        return hmac.new(self._namespace_key, payload, hashlib.sha256).hexdigest()[:32]

    def is_owner_message(self, update: dict[str, Any]) -> bool:
        message = update.get("message")
        if not isinstance(message, dict):
            return False
        sender = message.get("from") or {}
        chat = message.get("chat") or {}
        return (
            sender.get("id") == self.owner_id
            and chat.get("id") == self.owner_id
            and chat.get("type") == "private"
        )

    def is_owner_callback(self, update: dict[str, Any]) -> bool:
        callback = update.get("callback_query")
        if not isinstance(callback, dict):
            return False
        sender = callback.get("from") or {}
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        return (
            sender.get("id") == self.owner_id
            and chat.get("id") == self.owner_id
            and chat.get("type") == "private"
        )

    def denied_message_recipient(self, update: dict[str, Any]) -> int | None:
        message = update.get("message")
        if not isinstance(message, dict):
            return None
        chat = message.get("chat") or {}
        value = chat.get("id")
        return int(value) if isinstance(value, int) and chat.get("type") == "private" else None
