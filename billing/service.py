from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from nexora.limits import LimitsEngine
from nexora.plans import PlanCatalog, PlanError
from nexora.subscriptions import SubscriptionError, SubscriptionService
from nexora.usage import UsageMeter


class BillingAccessDenied(PermissionError):
    pass


class BillingLimitReached(RuntimeError):
    def __init__(self, metric: str) -> None:
        super().__init__("LIMIT_REACHED")
        self.metric = metric


class BillingFoundation:
    """Tenant-safe, payment-provider-free billing and quota facade."""

    def __init__(self, database: Any, audit: Any) -> None:
        self.database = database
        self.audit = audit
        self.plans = PlanCatalog(database)
        self.subscriptions = SubscriptionService(database, self.plans, audit)
        self.usage_meter = UsageMeter(database, audit)
        self.limits_engine = LimitsEngine(database, self.plans, self.subscriptions)

    def list_plans(self) -> list[dict[str, Any]]:
        return self.plans.list()

    def subscription(self, actor: str, organization_id: str) -> dict[str, Any]:
        self._require_tenant(actor, organization_id)
        return self._safe_subscription(self.subscriptions.get(organization_id))

    def usage(self, actor: str, organization_id: str) -> dict[str, Any]:
        self._require_tenant(actor, organization_id)
        return self.usage_meter.summary(organization_id)

    def limits(self, actor: str, organization_id: str) -> dict[str, Any]:
        self._require_tenant(actor, organization_id)
        return self.limits_engine.effective(organization_id)

    def check(self, actor: str, organization_id: str, metric: str, requested: int = 1) -> dict[str, Any]:
        self._require_tenant(actor, organization_id)
        try:
            decision = self.limits_engine.check(organization_id, metric, requested)
        except (SubscriptionError, PlanError) as exc:
            raise BillingAccessDenied("subscription unavailable") from exc
        if not decision.allowed:
            self._event(organization_id, "LIMIT_REACHED", "DENIED", {"metric": metric, "current": decision.current, "limit": decision.limit, "requested": requested})
            self.audit.record("LIMIT_REACHED", severity="WARNING", source="limits_engine", action_result="DENIED", organization_id=organization_id, metric=metric)
            raise BillingLimitReached(metric)
        return {"allowed": True, "metric": metric, "current": decision.current, "limit": decision.limit, "requested": requested}

    def record_runtime_usage(self, organization_id: str, workspace_id: str | None, metric: str, value: int, *, source: str) -> dict[str, Any]:
        return self.usage_meter.record(organization_id, workspace_id, metric, value, source=source)

    def change_plan(self, admin_actor: str, admin_namespace: str, organization_id: str, plan_id: str, approval_id: str, policy: Any) -> dict[str, Any]:
        self._require_admin(admin_actor, admin_namespace)
        self.plans.require(plan_id)
        action = f"billing:plan_change:{organization_id}:{plan_id}"
        self._consume_admin_approval(admin_actor, approval_id, action, policy)
        previous = self.subscriptions.get(organization_id)
        current = self.subscriptions.change(organization_id, plan_id)
        self._event(organization_id, "PLAN_CHANGED", "SUCCESS", {"from": previous["plan_id"], "to": plan_id, "approval_id": approval_id})
        self.audit.record("PLAN_CHANGED", source="billing_admin", action_result="SUCCESS", organization_id=organization_id, plan_id=plan_id, approval_id=approval_id)
        return self._safe_subscription(current)

    def set_organization_blocked(self, admin_actor: str, admin_namespace: str, organization_id: str, blocked: bool, approval_id: str, policy: Any) -> None:
        self._require_admin(admin_actor, admin_namespace)
        action = f"billing:organization_{'block' if blocked else 'unblock'}:{organization_id}"
        self._consume_admin_approval(admin_actor, approval_id, action, policy)
        self.database.set_organization_status(organization_id, "SUSPENDED" if blocked else "ACTIVE")
        self._event(organization_id, "ORGANIZATION_BLOCKED" if blocked else "ORGANIZATION_UNBLOCKED", "SUCCESS", {"approval_id": approval_id})
        self.audit.record("ORGANIZATION_BLOCKED" if blocked else "ORGANIZATION_UNBLOCKED", severity="SECURITY", source="billing_admin", action_result="SUCCESS", organization_id=organization_id, approval_id=approval_id)

    def admin_summary(self, actor: str, admin_namespace: str) -> dict[str, Any]:
        self._require_admin(actor, admin_namespace)
        items = []
        for organization in self.database.list_cloud_organizations():
            subscription = self.subscriptions.get(str(organization["id"]))
            usage = self.usage_meter.summary(str(organization["id"]))
            limits = self.limits_engine.effective(str(organization["id"]))
            item = {key: organization.get(key) for key in ("id", "name", "status", "created_at")}
            item.update({"plan_id": subscription["plan_id"], "subscription_status": subscription["status"], "usage": usage, "limits": limits})
            items.append(item)
        security = self.database.list_audit(limit=20, severity="SECURITY")
        return {
            "organizations": items,
            "plans": self.list_plans(),
            "system_health": {"database": "OK" if self.database.check() else "ERROR", "billing": "OK"},
            "security_events": [{"event": row.get("event"), "source": row.get("source"), "result": row.get("action_result"), "created_at": row.get("created_at")} for row in security],
        }

    def _require_tenant(self, actor: str, organization_id: str) -> str:
        role = self.database.organization_role(actor, organization_id)
        if role is None:
            self.audit.record("SECURITY_DENIED", severity="SECURITY", source="billing", action_result="BLOCKED", organization_id=organization_id, reason="tenant_access")
            raise BillingAccessDenied("resource not found or unavailable")
        return role

    @staticmethod
    def _require_admin(actor: str, admin_namespace: str) -> None:
        if not actor or actor != admin_namespace:
            raise BillingAccessDenied("admin access denied")

    def _consume_admin_approval(self, actor: str, approval_id: str, action: str, policy: Any) -> None:
        if not self.database.consume_team_approval(actor, approval_id, action):
            raise BillingAccessDenied("approval unavailable")
        decision = policy.evaluate("orchestrator", risk="HIGH", action_type="configuration_changes", approval_granted=True)
        if not decision.allowed:
            raise BillingAccessDenied("policy denied")

    def _event(self, organization_id: str, event: str, result: str, metadata: dict[str, Any]) -> None:
        self.database.insert_billing_event({
            "id": "BIL-" + secrets.token_hex(8).upper(), "organization_id": organization_id,
            "event": event, "result": result, "metadata": metadata,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    @staticmethod
    def _safe_subscription(value: dict[str, Any]) -> dict[str, Any]:
        return {key: value.get(key) for key in ("id", "organization_id", "plan_id", "plan_name", "status", "started_at", "expires_at", "created_at", "updated_at")}
