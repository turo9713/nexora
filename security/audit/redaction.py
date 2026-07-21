from __future__ import annotations

import re
from typing import Any


SENSITIVE_KEYS = {
    "authorization", "cookie", "password", "secret", "token", "api_key",
    "telegram_id", "telegram_user_id", "owner_id", "chat_id", "context",
    "prompt", "user_message", "private_key", "connection_string",
}
PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*)[^\r\n]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)((?:api[_-]?key|token|password|secret|cookie)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:postgres|mysql|mongodb(?:\+srv)?|redis)://[^\s]+"),
)


def redact_text(value: Any, limit: int = 4000) -> str:
    text = str(value).replace("\x00", "")
    for pattern in PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text[:limit]


def sanitize_metadata(value: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    if depth > 3:
        return {}
    result: dict[str, Any] = {}
    for index, (raw_key, raw_value) in enumerate(value.items()):
        if index >= 40:
            break
        key = str(raw_key)[:80]
        normalized = key.casefold().replace("-", "_")
        if normalized in SENSITIVE_KEYS or any(part in normalized for part in ("token", "secret", "password")):
            continue
        if isinstance(raw_value, dict):
            result[key] = sanitize_metadata(raw_value, depth + 1)
        elif isinstance(raw_value, (list, tuple)):
            result[key] = [redact_text(item, 500) for item in raw_value[:20]]
        elif raw_value is None or isinstance(raw_value, (bool, int, float)):
            result[key] = raw_value
        else:
            result[key] = redact_text(raw_value, 1000)
    return result
