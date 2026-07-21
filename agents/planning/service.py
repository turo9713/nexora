from __future__ import annotations

import json
from typing import Any

from nexora.agents.ecosystem_common import AgentEcosystemError, FORBIDDEN_WORDS, clean_text, identifier, row, utc_now


class PlanningEngine:
    """Deterministic plan compiler. It proposes bounded steps and never executes them."""

    def __init__(self, database: Any, security: Any, audit: Any) -> None:
        self.database, self.security, self.audit = database, security, audit

    def create(self, actor: str, workspace_id: str, goal: str) -> dict[str, Any]:
        context = self.security.authorize(actor, workspace_id, permission="tasks:create")
        goal = clean_text(goal, 1200)
        lowered = goal.casefold()
        if any(word in lowered for word in FORBIDDEN_WORDS):
            raise AgentEcosystemError("AGENT_PLAN_FORBIDDEN")
        steps = [
            {"position": 1, "agent_role": "orchestrator", "action": "clarify_goal", "tool": "text_generation", "risk": "LOW", "approval_required": False},
            {"position": 2, "agent_role": "research", "action": "collect_workspace_context", "tool": "workspace_read", "risk": "LOW", "approval_required": False},
            {"position": 3, "agent_role": "developer", "action": "produce_workspace_result", "tool": "workspace_write", "risk": "LOW", "approval_required": False},
            {"position": 4, "agent_role": "qa", "action": "validate_result", "tool": "test_runner", "risk": "LOW", "approval_required": False},
        ]
        for step in steps:
            self.security.authorize(actor, workspace_id, permission="tasks:create", tool=step["tool"], risk=step["risk"])
        plan_id, now = identifier("PLN"), utc_now()
        with self.database._connect() as connection:
            connection.execute("INSERT INTO agent_plans(id,workspace_id,owner_id,goal,status,risk,steps,created_at,updated_at) VALUES(?,?,?,?,'READY','LOW',?,?,?)", (plan_id, workspace_id, context["user_id"], goal, json.dumps(steps, separators=(",", ":")), now, now))
        self.database._secure_database()
        self.audit.record("AGENT_PLAN_CREATED", source="planning_engine", action_result="READY", workspace_id=workspace_id, plan_id=plan_id, step_count=len(steps))
        return {"id": plan_id, "goal": goal, "status": "READY", "risk": "LOW", "steps": steps, "created_at": now, "updated_at": now}

    def list(self, actor: str, workspace_id: str) -> list[dict[str, Any]]:
        self.security.authorize(actor, workspace_id, permission="tasks:read")
        with self.database._connect() as connection:
            values = connection.execute("SELECT id,goal,status,risk,steps,created_at,updated_at FROM agent_plans WHERE workspace_id=? ORDER BY created_at DESC", (workspace_id,)).fetchall()
        result=[]
        for value in values:
            item=row(value); item["steps"]=json.loads(item["steps"]); result.append(item)
        return result
