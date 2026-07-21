from __future__ import annotations

from nexora.dashboard.auth import Session


class DashboardPermissions:
    """Deny-by-default dashboard authorization independent of authentication."""

    ALLOWED = {
        "health:read",
        "tasks:read",
        "agents:read",
        "agents:request_change",
        "approvals:read",
        "approvals:decide",
        "audit:read",
        "skills:read",
        "skills:request_change",
        "api_keys:read",
        "api_keys:manage",
        "webhooks:read",
        "webhooks:manage",
        "metrics:read",
        "integrations:read",
        "templates:read",
        "templates:install",
        "playground:read",
    }

    def authorize(self, session: Session | None, permission: str) -> bool:
        return session is not None and session.role == "admin" and permission in self.ALLOWED
