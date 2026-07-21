from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any


class SubscriptionError(RuntimeError):
    pass


class SubscriptionService:
    ACTIVE = {"TRIAL", "ACTIVE"}

    def __init__(self, database: Any, plans: Any, audit: Any | None = None) -> None:
        self.database = database
        self.plans = plans
        self.audit = audit

    def get(self, organization_id: str) -> dict[str, Any]:
        subscription = self.database.ensure_subscription(organization_id)
        if subscription.pop("_created", False):
            self._event(organization_id, "SUBSCRIPTION_CREATED", "SUCCESS", {"plan_id": subscription["plan_id"], "status": subscription["status"]})
        expires_at = subscription.get("expires_at")
        if expires_at and subscription["status"] in self.ACTIVE:
            try:
                expired = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")).astimezone(timezone.utc) <= datetime.now(timezone.utc)
            except ValueError as exc:
                raise SubscriptionError("invalid subscription expiry") from exc
            if expired:
                self.database.set_subscription_status(organization_id, "EXPIRED")
                subscription = self.database.get_subscription(organization_id)
                self._event(organization_id, "SUBSCRIPTION_EXPIRED", "SUCCESS", {})
        if subscription is None:
            raise SubscriptionError("subscription unavailable")
        return subscription

    def require_active(self, organization_id: str) -> dict[str, Any]:
        subscription = self.get(organization_id)
        if subscription["status"] not in self.ACTIVE:
            raise SubscriptionError("subscription inactive")
        return subscription

    def change(self, organization_id: str, plan_id: str, *, status: str = "ACTIVE", expires_at: str | None = None) -> dict[str, Any]:
        self.plans.require(plan_id)
        self.get(organization_id)
        return self.database.set_subscription(organization_id, plan_id, status, expires_at)

    def cancel(self, organization_id: str) -> None:
        self.database.set_subscription_status(organization_id, "CANCELLED")
        self._event(organization_id, "SUBSCRIPTION_CANCELLED", "SUCCESS", {})

    def _event(self, organization_id: str, event: str, result: str, metadata: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.database.insert_billing_event({"id": "BIL-" + secrets.token_hex(8).upper(), "organization_id": organization_id, "event": event, "result": result, "metadata": metadata, "created_at": now})
        if self.audit is not None:
            self.audit.record(event, source="subscription_service", action_result=result, organization_id=organization_id)
