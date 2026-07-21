from __future__ import annotations

from dataclasses import dataclass


ROLES = ("OWNER", "ADMIN", "MANAGER", "OPERATOR", "VIEWER")
ROLE_RANK = {"OWNER": 50, "ADMIN": 40, "MANAGER": 30, "OPERATOR": 20, "VIEWER": 10}
ROLE_PERMISSIONS = {
    "OWNER": {"organization:manage", "workspace:create", "workspace:manage", "members:manage", "billing:prepare", "security:manage", "agents:manage", "skills:manage", "tasks:create", "tasks:manage", "tasks:read", "comments:create", "knowledge:read", "knowledge:write", "audit:read"},
    "ADMIN": {"workspace:create", "workspace:manage", "members:manage", "agents:manage", "skills:manage", "tasks:create", "tasks:manage", "tasks:read", "comments:create", "knowledge:read", "knowledge:write", "audit:read"},
    "MANAGER": {"tasks:create", "tasks:manage", "tasks:read", "comments:create", "knowledge:read", "knowledge:write", "audit:read"},
    "OPERATOR": {"tasks:create", "tasks:read", "comments:create", "knowledge:read"},
    "VIEWER": {"tasks:read", "knowledge:read"},
}


@dataclass(frozen=True)
class RBACDecision:
    allowed: bool
    reason: str
    role: str | None
    permission: str


class RBAC:
    """Fail-closed role checks. Missing or unknown roles have no permissions."""

    def evaluate(self, role: str | None, permission: str) -> RBACDecision:
        normalized = str(role or "").upper()
        if normalized not in ROLE_PERMISSIONS:
            return RBACDecision(False, "unknown_or_missing_role", None, permission)
        allowed = permission in ROLE_PERMISSIONS[normalized]
        return RBACDecision(allowed, "allowed" if allowed else "permission_denied", normalized, permission)

    def can_assign(self, actor_role: str | None, target_role: str) -> bool:
        actor = str(actor_role or "").upper()
        target = str(target_role).upper()
        if actor not in ROLE_RANK or target not in ROLE_RANK:
            return False
        if actor == "OWNER":
            return True
        return actor == "ADMIN" and ROLE_RANK[target] < ROLE_RANK[actor]
