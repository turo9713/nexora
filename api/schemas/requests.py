from __future__ import annotations

import re
from typing import Any


class APIValidationError(ValueError):
    pass


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
TENANT_ID = re.compile(r"^(?:ORG|WS)-[A-F0-9]{12}$")
WEBHOOK_EVENTS = {"TASK_CREATED", "TASK_COMPLETED", "TASK_FAILED", "APPROVAL_REQUIRED", "SECURITY_EVENT"}


def validate_task_create(value: dict[str, Any]) -> dict[str, str]:
    if set(value) - {"title", "agent", "skill", "workspace_id"}:
        raise APIValidationError("unsupported task field")
    title = " ".join(str(value.get("title") or "").replace("\x00", "").split())[:200]
    agent = str(value.get("agent") or "").casefold()
    skill = str(value.get("skill") or "").casefold()
    if not title or not IDENTIFIER.fullmatch(agent) or not IDENTIFIER.fullmatch(skill):
        raise APIValidationError("invalid task request")
    result = {"title": title, "agent": agent, "skill": skill}
    workspace_id = str(value.get("workspace_id") or "")
    if workspace_id:
        if not TENANT_ID.fullmatch(workspace_id) or not workspace_id.startswith("WS-"):
            raise APIValidationError("invalid workspace")
        result["workspace_id"] = workspace_id
    return result


def validate_workspace_create(value: dict[str, Any]) -> dict[str, str]:
    if set(value) - {"organization_id", "name", "description"}:
        raise APIValidationError("unsupported workspace field")
    organization_id = str(value.get("organization_id") or "")
    name = " ".join(str(value.get("name") or "").split())[:120]
    description = str(value.get("description") or "")[:1000]
    if not organization_id.startswith("ORG-") or not TENANT_ID.fullmatch(organization_id) or len(name) < 2:
        raise APIValidationError("invalid workspace request")
    return {"organization_id": organization_id, "name": name, "description": description}


def validate_invite(value: dict[str, Any]) -> dict[str, str]:
    if set(value) - {"workspace_id", "email_hash", "display_name", "role", "approval_id"}:
        raise APIValidationError("unsupported invite field")
    result = {key: str(value.get(key) or "") for key in ("workspace_id", "email_hash", "display_name", "role", "approval_id")}
    if not result["workspace_id"].startswith("WS-") or not TENANT_ID.fullmatch(result["workspace_id"]):
        raise APIValidationError("invalid invite request")
    return result


def validate_knowledge(value: dict[str, Any]) -> dict[str, str]:
    if set(value) - {"workspace_id", "name", "type", "access_level", "content"}:
        raise APIValidationError("unsupported knowledge field")
    result = {key: str(value.get(key) or "") for key in ("workspace_id", "name", "type", "access_level", "content")}
    if not result["workspace_id"].startswith("WS-") or not TENANT_ID.fullmatch(result["workspace_id"]):
        raise APIValidationError("invalid knowledge request")
    return result


def validate_webhook_create(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) - {"url", "events"}:
        raise APIValidationError("unsupported webhook field")
    url = str(value.get("url") or "")[:500]
    events = sorted(set(str(item) for item in value.get("events", []))) if isinstance(value.get("events"), list) else []
    if not url.startswith("https://") or not events or any(event not in WEBHOOK_EVENTS for event in events):
        raise APIValidationError("invalid webhook request")
    return {"url": url, "events": events}
