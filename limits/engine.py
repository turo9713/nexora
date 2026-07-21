from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class LimitDecision:
    allowed: bool
    code: str
    metric: str
    current: int
    limit: int | None
    requested: int


class LimitsEngine:
    METRICS = {"workspace_limit", "members_limit", "agents_limit", "tasks_monthly", "storage_bytes"}

    def __init__(self, database: Any, plans: Any, subscriptions: Any) -> None:
        self.database = database
        self.plans = plans
        self.subscriptions = subscriptions

    def effective(self, organization_id: str) -> dict[str, Any]:
        subscription = self.subscriptions.get(organization_id)
        plan = self.plans.require(subscription["plan_id"])
        values = dict(plan["limits"])
        values.update(self.database.get_limit_overrides(organization_id))
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        current = self.database.organization_resource_usage(organization_id, month)
        return {"plan": plan["id"], "subscription_status": subscription["status"], "limits": values, "current": current}

    def check(self, organization_id: str, metric: str, requested: int = 1) -> LimitDecision:
        if metric not in self.METRICS or not isinstance(requested, int) or requested < 0:
            return LimitDecision(False, "LIMIT_INVALID", metric, 0, 0, requested)
        self.subscriptions.require_active(organization_id)
        effective = self.effective(organization_id)
        current = int(effective["current"].get(metric, 0))
        maximum = effective["limits"].get(metric)
        if maximum is None:
            return LimitDecision(True, "ALLOWED", metric, current, None, requested)
        limit = int(maximum)
        allowed = current + requested <= limit
        return LimitDecision(allowed, "ALLOWED" if allowed else "LIMIT_REACHED", metric, current, limit, requested)
