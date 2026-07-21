from __future__ import annotations

from typing import Any


class NexoraSDK:
    """In-process declarative SDK. It delegates every operation to policy-checked services."""

    def __init__(self, ecosystem: Any, actor: str, workspace_id: str) -> None:
        self._ecosystem, self._actor, self._workspace = ecosystem, actor, workspace_id

    def create_agent(self, manifest: dict[str, Any], approval_id: str) -> dict[str, Any]:
        return self._ecosystem.builder.create(self._actor, self._workspace, manifest, approval_id=approval_id)

    def create_team(self, name: str, leader_agent_id: str, workflow: list[str], approval_id: str) -> dict[str, Any]:
        return self._ecosystem.teams.create(self._actor, self._workspace, name, leader_agent_id, workflow, approval_id=approval_id)

    def create_plan(self, goal: str) -> dict[str, Any]:
        return self._ecosystem.planning.create(self._actor, self._workspace, goal)

    def connect_skill(self, agent_id: str, skill_id: str) -> dict[str, str]:
        agent = self._ecosystem.builder.get(self._actor, self._workspace, agent_id)
        if agent is None or skill_id not in agent["manifest"]["skills"]:
            raise ValueError("SDK_SKILL_NOT_DECLARED")
        return {"agent_id": agent_id, "skill_id": skill_id, "status": "DECLARED"}

    def start_workflow(self, goal: str) -> dict[str, Any]:
        plan = self.create_plan(goal)
        return {"plan_id": plan["id"], "status": plan["status"], "execution": "not_started", "steps": plan["steps"]}

    def result(self, plan_id: str) -> dict[str, str]:
        return {"plan_id": str(plan_id), "status": "READY", "execution": "not_started"}
