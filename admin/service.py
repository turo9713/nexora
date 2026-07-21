from __future__ import annotations

from typing import Any


class AdminConsole:
    def __init__(self, billing: Any, namespace: str, policy: Any) -> None:
        self.billing = billing
        self.namespace = namespace
        self.policy = policy

    def summary(self, actor: str) -> dict[str, Any]:
        return self.billing.admin_summary(actor, self.namespace)

    def change_plan(self, actor: str, organization_id: str, plan_id: str, approval_id: str) -> dict[str, Any]:
        return self.billing.change_plan(actor, self.namespace, organization_id, plan_id, approval_id, self.policy)

    def block(self, actor: str, organization_id: str, blocked: bool, approval_id: str) -> None:
        self.billing.set_organization_blocked(actor, self.namespace, organization_id, blocked, approval_id, self.policy)
