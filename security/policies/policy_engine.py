from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nexora.agents.registry import AgentRegistry, RegistryError


FORBIDDEN_ACTIONS = {
    "secrets_access",
    "security_policy_changes",
    "sandbox_disable",
    "root",
    "financial_operations",
    "firewall_changes",
    "ssh_changes",
}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    reason: str
    agent_id: str
    risk: str


class PolicyEngine:
    """Minimal deny-by-default authorization layer for agent operations."""

    def __init__(self, registry: AgentRegistry, workspace_root: Path, status_resolver: object | None = None) -> None:
        self.registry = registry
        self.workspace_root = Path(workspace_root).resolve()
        self.status_resolver = status_resolver

    def evaluate(
        self,
        agent_id: str,
        *,
        tool: str | None = None,
        path: str | Path | None = None,
        risk: str = "LOW",
        action_type: str | None = None,
        approval_granted: bool = False,
    ) -> PolicyDecision:
        normalized_risk = str(risk).upper()
        try:
            manifest = self.registry.require(agent_id)
        except RegistryError:
            return PolicyDecision(False, False, "unknown_or_disabled_agent", agent_id, normalized_risk)
        if self.status_resolver is not None:
            override = self.status_resolver(manifest.id)  # type: ignore[operator]
            if override is False:
                return PolicyDecision(False, False, "agent_disabled_by_override", manifest.id, normalized_risk)

        if normalized_risk not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            return PolicyDecision(False, False, "invalid_risk", manifest.id, normalized_risk)
        if normalized_risk == "CRITICAL" or action_type in FORBIDDEN_ACTIONS:
            return PolicyDecision(False, False, "forbidden_action", manifest.id, normalized_risk)
        if tool is not None:
            if tool in manifest.tools_denied or tool not in manifest.tools_allowed:
                return PolicyDecision(False, False, "tool_not_allowed", manifest.id, normalized_risk)
        if path is not None and not self._inside_workspace(path):
            return PolicyDecision(False, False, "path_outside_workspace", manifest.id, normalized_risk)

        needs_approval = (
            normalized_risk in {"MEDIUM", "HIGH"}
            or (action_type is not None and action_type in manifest.approval_required)
        )
        if needs_approval and not approval_granted:
            return PolicyDecision(False, True, "approval_required", manifest.id, normalized_risk)
        return PolicyDecision(True, needs_approval, "allowed", manifest.id, normalized_risk)

    def authorize_route(self, route: list[str] | tuple[str, ...]) -> PolicyDecision:
        for agent_id in route:
            if agent_id in {"owner", "user"}:
                continue
            decision = self.evaluate(agent_id)
            if not decision.allowed:
                return decision
        return PolicyDecision(True, False, "allowed", "route", "LOW")

    def _inside_workspace(self, value: str | Path) -> bool:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        candidate = candidate.resolve(strict=False)
        return candidate == self.workspace_root or self.workspace_root in candidate.parents
