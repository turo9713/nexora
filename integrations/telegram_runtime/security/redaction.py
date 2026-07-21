from __future__ import annotations

import re
from typing import Any


REDACTION_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*)[^\r\n]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)((?:api[_-]?key|token|password|secret|cookie)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:postgres|mysql|mongodb(?:\+srv)?|redis)://[^\s]+"),
)


def redact_text(value: Any) -> str:
    text = str(value).replace("\x00", "")
    for pattern in REDACTION_PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text[:4000]


def safe_error_code(error: BaseException) -> str:
    message = str(error).casefold()
    name = type(error).__name__.casefold()
    if "timeout" in message or "timed out" in message:
        return "NX_TIMEOUT"
    if "permission" in message or "denied" in message:
        return "NX_PERMISSION_DENIED"
    if "validation" in message or "schema" in message or "jsonschema" in name:
        return "NX_VALIDATION_ERROR"
    if "provider" in message or "transport" in message or "gateway" in message:
        return "NX_PROVIDER_ERROR"
    if "cancel" in message:
        return "NX_TASK_CANCELLED"
    return "NX_INTERNAL_ERROR"
