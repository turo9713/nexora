from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from nexora.billing import BillingAccessDenied


class CloudManager:
    """Metadata-only tenant provisioning; allocates no external infrastructure."""

    def __init__(self, database: Any, teams: Any, billing: Any, audit: Any, admin_namespace: str, policy: Any) -> None:
        self.database = database
        self.teams = teams
        self.billing = billing
        self.audit = audit
        self.admin_namespace = admin_namespace
        self.policy = policy

    def provision(self, actor: str, customer_namespace: str, organization_name: str, workspace_name: str, plan_id: str, approval_id: str) -> dict[str, Any]:
        if actor != self.admin_namespace or not customer_namespace or customer_namespace == actor:
            raise BillingAccessDenied("cloud provisioning denied")
        if not self.database.consume_team_approval(actor, approval_id, "cloud:tenant_provision"):
            raise BillingAccessDenied("approval unavailable")
        decision = self.policy.evaluate("orchestrator", risk="HIGH", action_type="configuration_changes", approval_granted=True)
        if not decision.allowed:
            raise BillingAccessDenied("policy denied")
        self.billing.plans.require(plan_id)
        organization = self.teams.create_organization(customer_namespace, organization_name)
        self.billing.subscriptions.change(organization["id"], plan_id)
        workspace = self.teams.create_workspace(customer_namespace, organization["id"], workspace_name, "Provisioned cloud tenant workspace")
        now = datetime.now(timezone.utc).isoformat()
        resource = {"id": "CLR-" + secrets.token_hex(6).upper(), "organization_id": organization["id"], "workspace_id": workspace["id"], "resource_type": "TENANT_METADATA", "status": "READY", "metadata": {"external_allocation": False}, "created_at": now, "updated_at": now}
        self.database.add_cloud_resource(resource)
        self.billing.record_runtime_usage(organization["id"], workspace["id"], "files", 0, source="cloud_manager")
        self.audit.record("TENANT_PROVISIONED", source="cloud_manager", action_result="READY", organization_id=organization["id"], workspace_id=workspace["id"], approval_id=approval_id)
        return {"organization": organization, "workspace": workspace, "subscription": self.billing.subscription(customer_namespace, organization["id"]), "resource": {key: resource[key] for key in ("id", "resource_type", "status")}}
