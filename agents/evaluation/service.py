from __future__ import annotations

from typing import Any

from nexora.agents.ecosystem_common import AgentEcosystemError, identifier, row, utc_now


class AgentEvaluation:
    METRICS = ("accuracy", "reliability", "safety", "speed", "cost")

    def __init__(self, database: Any, security: Any, audit: Any) -> None:
        self.database, self.security, self.audit = database, security, audit

    def record(self, actor: str, workspace_id: str, agent_id: str, metrics: dict[str, int], *, task_id: str | None = None, source: str = "agent_runner") -> dict[str, Any]:
        context = self.security.authorize(actor, workspace_id, permission="tasks:manage")
        if source not in {"agent_runner", "workflow_engine", "evaluation_service"} or set(metrics) != set(self.METRICS):
            raise AgentEcosystemError("AGENT_EVALUATION_INVALID")
        values = {key: int(metrics[key]) for key in self.METRICS}
        if any(value < 0 or value > 100 for value in values.values()):
            raise AgentEcosystemError("AGENT_EVALUATION_INVALID")
        score = round(values["accuracy"]*.3 + values["reliability"]*.25 + values["safety"]*.25 + values["speed"]*.1 + values["cost"]*.1)
        grade = "A+" if score >= 95 else "A" if score >= 85 else "B" if score >= 75 else "C" if score >= 65 else "D" if score >= 50 else "F"
        result = {"id": identifier("EVA"), "workspace_id": workspace_id, "owner_id": context["user_id"], "agent_id": agent_id, "task_id": task_id, **values, "score": score, "grade": grade, "created_at": utc_now()}
        with self.database._connect() as connection:
            connection.execute("INSERT INTO agent_evaluations(id,workspace_id,owner_id,agent_id,task_id,accuracy,reliability,safety,speed,cost,score,grade,created_at) VALUES(:id,:workspace_id,:owner_id,:agent_id,:task_id,:accuracy,:reliability,:safety,:speed,:cost,:score,:grade,:created_at)", result)
        self.database._secure_database()
        self.audit.record("AGENT_EVALUATED", source=source, action_result="SUCCESS", workspace_id=workspace_id, agent_id=agent_id, score=score, grade=grade)
        result.pop("owner_id")
        return result

    def list(self, actor: str, workspace_id: str, agent_id: str | None = None) -> list[dict[str, Any]]:
        self.security.authorize(actor, workspace_id, permission="tasks:read")
        sql="SELECT id,agent_id,task_id,accuracy,reliability,safety,speed,cost,score,grade,created_at FROM agent_evaluations WHERE workspace_id=?"
        params: tuple[Any,...]=(workspace_id,)
        if agent_id: sql += " AND agent_id=?"; params += (agent_id,)
        sql += " ORDER BY created_at DESC LIMIT 100"
        with self.database._connect() as connection: values=connection.execute(sql,params).fetchall()
        return [row(value) for value in values]
