from __future__ import annotations

import re
from typing import Any


class APIValidationError(ValueError):
    pass


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
WEBHOOK_EVENTS = {"TASK_CREATED", "TASK_COMPLETED", "TASK_FAILED", "APPROVAL_REQUIRED", "SECURITY_EVENT"}


def validate_task_create(value: dict[str, Any]) -> dict[str, str]:
    if set(value) - {"title", "agent", "skill"}:
        raise APIValidationError("unsupported task field")
    title = " ".join(str(value.get("title") or "").replace("\x00", "").split())[:200]
    agent = str(value.get("agent") or "").casefold()
    skill = str(value.get("skill") or "").casefold()
    if not title or not IDENTIFIER.fullmatch(agent) or not IDENTIFIER.fullmatch(skill):
        raise APIValidationError("invalid task request")
    return {"title": title, "agent": agent, "skill": skill}


def validate_webhook_create(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) - {"url", "events"}:
        raise APIValidationError("unsupported webhook field")
    url = str(value.get("url") or "")[:500]
    events = sorted(set(str(item) for item in value.get("events", []))) if isinstance(value.get("events"), list) else []
    if not url.startswith("https://") or not events or any(event not in WEBHOOK_EVENTS for event in events):
        raise APIValidationError("invalid webhook request")
    return {"url": url, "events": events}
