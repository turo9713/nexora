from __future__ import annotations

from typing import Any

from nexora.agents.ecosystem_common import AgentEcosystemDenied, FORBIDDEN_WORDS


class AgentSecurityGuard:
    """One fail-closed check for identity, tenant, tool, memory and approval boundaries."""

    def __init__(self, teams: Any, policy: Any, audit: Any) -> None:
        self.teams, self.policy, self.audit = teams, policy, audit

    def authorize(self, actor: str, workspace_id: str, *, permission: str, tool: str | None = None,
                  memory_scope: str | None = None, risk: str = "LOW", approval_granted: bool = False) -> dict[str, Any]:
        try:
            context = self.teams.workspace_context(actor, workspace_id, permission)
        except Exception as exc:
            self._deny(workspace_id, "tenant_or_role_denied")
            raise AgentEcosystemDenied("resource not found or unavailable") from exc
        if tool and (tool.casefold() in FORBIDDEN_WORDS or tool not in {"text_generation", "research", "code_analysis", "test_runner", "workspace_read", "workspace_write", "knowledge_read"}):
            self._deny(workspace_id, "tool_denied")
        if memory_scope and memory_scope not in {"PERSONAL", "WORKSPACE", "AGENT"}:
            self._deny(workspace_id, "memory_scope_denied")
        decision = self.policy.evaluate("orchestrator", risk=risk, action_type="configuration_changes" if risk in {"MEDIUM", "HIGH"} else None, approval_granted=approval_granted)
        if not decision.allowed:
            self._deny(workspace_id, decision.reason)
        return context

    def authorize_change(self, actor: str, workspace_id: str, *, permission: str, action_type: str, approval_id: str) -> dict[str, Any]:
        try:
            context = self.teams.workspace_context(actor, workspace_id, permission)
            self.teams._require_approval(actor, action_type, approval_id)
        except Exception as exc:
            self._deny(workspace_id, "approval_or_role_denied")
            raise AgentEcosystemDenied("resource not found or unavailable") from exc
        return context

    def _deny(self, workspace_id: str, reason: str) -> None:
        self.audit.record("AGENT_SECURITY_DENIED", severity="SECURITY", source="agent_security", action_result="BLOCKED", workspace_id=workspace_id, reason=reason)
        raise AgentEcosystemDenied("resource not found or unavailable")
