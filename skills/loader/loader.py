from __future__ import annotations

from dataclasses import dataclass

from nexora.skills.policies import SkillPolicyEngine


@dataclass(frozen=True)
class SkillActivation:
    skill_id: str
    version: str
    agent: str
    tools: tuple[str, ...]
    status: str = "ACTIVE"


class SkillLoader:
    """Return validated capability metadata; never import or execute plugin code."""

    def __init__(self, registry: object, policy: SkillPolicyEngine, agent_policy: object) -> None:
        self.registry = registry
        self.policy = policy
        self.agent_policy = agent_policy

    def activate(
        self,
        skill_id: str,
        *,
        agent_id: str,
        tool: str | None = None,
        path: str | None = None,
        network_mode: str = "none",
        approval_granted: bool = False,
    ) -> SkillActivation:
        manifest = self.registry.require_active(skill_id)  # type: ignore[attr-defined]
        agent_decision = self.agent_policy.evaluate(  # type: ignore[attr-defined]
            agent_id,
            risk=manifest.risk.upper(),
            action_type="skill_activation",
            approval_granted=approval_granted,
        )
        if not agent_decision.allowed:
            raise PermissionError("approval_required" if agent_decision.requires_approval else agent_decision.reason)
        decision = self.policy.evaluate(
            manifest,
            agent_id=agent_id,
            tool=tool,
            path=path,
            network_mode=network_mode,
        )
        if not decision.allowed:
            raise PermissionError(decision.reason)
        if decision.requires_approval and not approval_granted:
            raise PermissionError("approval_required")
        return SkillActivation(manifest.id, manifest.version, manifest.agent, manifest.tools)
