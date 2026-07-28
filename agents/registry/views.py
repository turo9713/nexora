from __future__ import annotations

from typing import Any

from .registry import AgentManifest


def safe_agent_view(manifest: AgentManifest, *, enabled: bool, task_summary: dict[str, Any]) -> dict[str, Any]:
    """Return the public, read-only Agent Control Center projection."""

    active_tasks = max(0, int(task_summary.get("active_tasks") or 0))
    status = "DISABLED" if not enabled else ("ACTIVE" if active_tasks else "IDLE")
    allowed_tools = list(manifest.tools_allowed)
    risk_level = manifest.risk_level
    return {
        "id": manifest.id,
        "name": manifest.name,
        "description": manifest.description,
        "status": status,
        "enabled": enabled,
        "role": manifest.system_role,
        "risk_level": risk_level,
        "permissions": list(manifest.permissions),
        "allowed_tools": allowed_tools,
        "restrictions": list(manifest.restrictions),
        "completed_tasks": max(0, int(task_summary.get("completed_tasks") or 0)),
        "last_activity": task_summary.get("last_activity"),
        # Backward-compatible aliases for the pre-v3.2 internal Dashboard API.
        "risk": risk_level,
        "tools": allowed_tools,
    }
