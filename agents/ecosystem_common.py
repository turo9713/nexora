from __future__ import annotations

import hashlib
import json
import re
import secrets
from typing import Any

from nexora.integrations.telegram_runtime.services.progress_service import utc_now
from nexora.security.audit.redaction import redact_text, sanitize_metadata


ID = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SAFE_TOOLS = {"text_generation", "research", "code_analysis", "test_runner", "workspace_read", "workspace_write", "knowledge_read"}
SAFE_PERMISSIONS = {"workspace:read", "workspace:write", "drafts:write", "knowledge:read", "network:search"}
FORBIDDEN_WORDS = {"shell", "sudo", "root", "docker", "secret", "token", "credential", "private_key", "production"}


class AgentEcosystemError(ValueError):
    pass


class AgentEcosystemDenied(PermissionError):
    pass


def identifier(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(6).upper()}"


def clean_text(value: Any, limit: int = 1000, *, minimum: int = 2) -> str:
    result = redact_text(" ".join(str(value or "").split()), limit).strip()
    if len(result) < minimum:
        raise AgentEcosystemError("AGENT_FIELD_INVALID")
    return result


def canonical(value: dict[str, Any]) -> tuple[str, str]:
    payload = json.dumps(sanitize_metadata(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def safe_list(values: Any, allowed: set[str], code: str) -> list[str]:
    if not isinstance(values, list) or len(values) > 32:
        raise AgentEcosystemError(code)
    normalized = list(dict.fromkeys(str(item).strip().lower() for item in values))
    if any(not item or item not in allowed for item in normalized):
        raise AgentEcosystemError(code)
    return normalized


def row(value: Any) -> dict[str, Any]:
    return dict(value) if value is not None else {}


__all__ = ["AgentEcosystemDenied", "AgentEcosystemError", "FORBIDDEN_WORDS", "ID", "SAFE_PERMISSIONS", "SAFE_TOOLS", "SEMVER", "canonical", "clean_text", "identifier", "row", "safe_list", "utc_now"]
