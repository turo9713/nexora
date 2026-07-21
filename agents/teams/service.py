from __future__ import annotations

import json
from typing import Any

from nexora.agents.ecosystem_common import AgentEcosystemError, clean_text, identifier, row, utc_now


class AgentTeamService:
    ALLOWED_ROLES = {"LEADER", "SPECIALIST", "REVIEWER"}

    def __init__(self, database: Any, security: Any, audit: Any) -> None:
        self.database, self.security, self.audit = database, security, audit

    def create(self, actor: str, workspace_id: str, name: str, leader_agent_id: str, workflow: list[str], *, approval_id: str) -> dict[str, Any]:
        ordered = list(dict.fromkeys(str(value) for value in workflow))
        if not 1 <= len(ordered) <= 16 or leader_agent_id not in ordered:
            raise AgentEcosystemError("AGENT_TEAM_INVALID")
        context = self.security.authorize_change(actor, workspace_id, permission="agents:manage", action_type=f"agent_team:create:{workspace_id}", approval_id=approval_id)
        self._require_agents(workspace_id, ordered)
        team_id, now = identifier("ATM"), utc_now()
        with self.database._connect() as connection:
            connection.execute("INSERT INTO agent_teams(id,workspace_id,owner_id,name,leader_agent_id,workflow,status,created_at,updated_at) VALUES(?,?,?,?,?,?,'ACTIVE',?,?)",
                               (team_id, workspace_id, context["user_id"], clean_text(name, 120), leader_agent_id, json.dumps(ordered), now, now))
            for position, agent_id in enumerate(ordered):
                role = "LEADER" if agent_id == leader_agent_id else "SPECIALIST"
                connection.execute("INSERT INTO team_members(id,team_id,agent_id,role,position,created_at) VALUES(?,?,?,?,?,?)", (identifier("TMB"), team_id, agent_id, role, position, now))
        self.database._secure_database()
        self.audit.record("AGENT_TEAM_CREATED", source="agent_teams", action_result="SUCCESS", workspace_id=workspace_id, team_id=team_id)
        return self.get(actor, workspace_id, team_id) or {}

    def set_member(self, actor: str, workspace_id: str, team_id: str, agent_id: str, role_name: str, *, approval_id: str) -> None:
        self.security.authorize_change(actor, workspace_id, permission="agents:manage", action_type=f"agent_team:member_change:{workspace_id}:{team_id}", approval_id=approval_id)
        role_name = str(role_name).upper()
        if role_name not in self.ALLOWED_ROLES:
            raise AgentEcosystemError("AGENT_TEAM_ROLE_INVALID")
        self._require_agents(workspace_id, [agent_id])
        with self.database._connect() as connection:
            team = connection.execute("SELECT id FROM agent_teams WHERE id=? AND workspace_id=?", (team_id, workspace_id)).fetchone()
            if team is None:
                raise AgentEcosystemError("AGENT_TEAM_NOT_FOUND")
            position = connection.execute("SELECT COALESCE(MAX(position),-1)+1 FROM team_members WHERE team_id=?", (team_id,)).fetchone()[0]
            connection.execute("INSERT OR IGNORE INTO team_members(id,team_id,agent_id,role,position,created_at) VALUES(?,?,?,?,?,?)", (identifier("TMB"), team_id, agent_id, role_name, position, utc_now()))
        self.audit.record("AGENT_TEAM_MEMBER_CHANGED", source="agent_teams", action_result="SUCCESS", workspace_id=workspace_id, team_id=team_id, agent_id=agent_id)

    def remove_member(self, actor: str, workspace_id: str, team_id: str, agent_id: str, *, approval_id: str) -> None:
        self.security.authorize_change(actor, workspace_id, permission="agents:manage", action_type=f"agent_team:member_change:{workspace_id}:{team_id}", approval_id=approval_id)
        with self.database._connect() as connection:
            team = connection.execute("SELECT leader_agent_id FROM agent_teams WHERE id=? AND workspace_id=?", (team_id, workspace_id)).fetchone()
            if team is None or team["leader_agent_id"] == agent_id:
                raise AgentEcosystemError("AGENT_TEAM_MEMBER_UNAVAILABLE")
            connection.execute("DELETE FROM team_members WHERE team_id=? AND agent_id=?", (team_id, agent_id))
        self.audit.record("AGENT_TEAM_MEMBER_CHANGED", source="agent_teams", action_result="REMOVED", workspace_id=workspace_id, team_id=team_id, agent_id=agent_id)

    def list(self, actor: str, workspace_id: str) -> list[dict[str, Any]]:
        self.security.authorize(actor, workspace_id, permission="tasks:read")
        with self.database._connect() as connection:
            values = connection.execute("SELECT id,name,leader_agent_id,status,created_at,updated_at FROM agent_teams WHERE workspace_id=? ORDER BY name", (workspace_id,)).fetchall()
        return [row(value) for value in values]

    def get(self, actor: str, workspace_id: str, team_id: str) -> dict[str, Any] | None:
        self.security.authorize(actor, workspace_id, permission="tasks:read")
        with self.database._connect() as connection:
            value = connection.execute("SELECT id,name,leader_agent_id,workflow,status,created_at,updated_at FROM agent_teams WHERE id=? AND workspace_id=?", (team_id, workspace_id)).fetchone()
            members = connection.execute("SELECT agent_id,role,position FROM team_members WHERE team_id=? ORDER BY position", (team_id,)).fetchall() if value else []
        if value is None:
            return None
        result = row(value); result["workflow"] = json.loads(result["workflow"]); result["members"] = [row(item) for item in members]
        return result

    def _require_agents(self, workspace_id: str, agent_ids: list[str]) -> None:
        with self.database._connect() as connection:
            found = {value[0] for value in connection.execute("SELECT id FROM agents WHERE workspace_id=? AND status='ACTIVE'", (workspace_id,)).fetchall()}
        if any(agent_id not in found for agent_id in agent_ids):
            raise AgentEcosystemError("AGENT_TEAM_UNKNOWN_AGENT")
