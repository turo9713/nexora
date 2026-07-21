from __future__ import annotations

import json
from typing import Any

from nexora.agents.ecosystem_common import ID, SEMVER, SAFE_PERMISSIONS, SAFE_TOOLS, AgentEcosystemError, canonical, clean_text, identifier, row, safe_list, utc_now


class AgentBuilder:
    """Builds declarative agent manifests only; executable payloads are never accepted."""

    def __init__(self, database: Any, security: Any, audit: Any) -> None:
        self.database, self.security, self.audit = database, security, audit

    def create(self, actor: str, workspace_id: str, value: dict[str, Any], *, approval_id: str) -> dict[str, Any]:
        manifest = self.validate(value)
        context = self.security.authorize_change(actor, workspace_id, permission="agents:manage", action_type=f"agent_builder:create:{workspace_id}:{manifest['id']}:{manifest['version']}", approval_id=approval_id)
        payload, checksum = canonical(manifest)
        now, owner_id = utc_now(), int(context["user_id"])
        with self.database._connect() as connection:
            connection.execute("INSERT INTO agents(id,workspace_id,owner_id,name,role,goal,status,current_version,created_at,updated_at) VALUES(?,?,?,?,?,?,'ACTIVE',?,?,?)",
                               (manifest["id"], workspace_id, owner_id, manifest["name"], manifest["role"], manifest["goal"], manifest["version"], now, now))
            connection.execute("INSERT INTO agent_versions(id,agent_id,workspace_id,version,manifest,checksum,status,created_at) VALUES(?,?,?,?,?,?,'ACTIVE',?)",
                               (identifier("AVR"), manifest["id"], workspace_id, manifest["version"], payload, checksum, now))
        self.database._secure_database()
        self.audit.record("AGENT_CREATED", source="agent_builder", action_result="SUCCESS", workspace_id=workspace_id, agent_id=manifest["id"], version=manifest["version"])
        return {**manifest, "status": "ACTIVE", "checksum": checksum}

    def validate(self, value: dict[str, Any]) -> dict[str, Any]:
        allowed = {"id", "name", "version", "description", "goal", "role", "skills", "knowledge", "tools", "permissions", "memory_scope", "approval_rules"}
        required = allowed
        if not isinstance(value, dict) or not required.issubset(value) or not set(value).issubset(allowed):
            raise AgentEcosystemError("AGENT_MANIFEST_INVALID")
        agent_id, version = str(value["id"]).lower(), str(value["version"])
        if not ID.fullmatch(agent_id) or not SEMVER.fullmatch(version):
            raise AgentEcosystemError("AGENT_ID_OR_VERSION_INVALID")
        memory = str(value["memory_scope"]).upper()
        if memory not in {"PERSONAL", "WORKSPACE", "AGENT"}:
            raise AgentEcosystemError("AGENT_MEMORY_SCOPE_INVALID")
        skills = value["skills"]
        knowledge = value["knowledge"]
        approvals = value["approval_rules"]
        if not isinstance(skills, list) or not isinstance(knowledge, list) or not isinstance(approvals, list) or any(len(x) > 32 for x in (skills, knowledge, approvals)):
            raise AgentEcosystemError("AGENT_COLLECTION_INVALID")
        return {
            "id": agent_id, "name": clean_text(value["name"], 120), "version": version,
            "description": clean_text(value["description"], 1000), "goal": clean_text(value["goal"], 1000),
            "role": clean_text(value["role"], 120),
            "skills": [clean_text(item, 64) for item in skills],
            "knowledge": [clean_text(item, 100) for item in knowledge],
            "tools": safe_list(value["tools"], SAFE_TOOLS, "AGENT_TOOL_DENIED"),
            "permissions": safe_list(value["permissions"], SAFE_PERMISSIONS, "AGENT_PERMISSION_DENIED"),
            "memory_scope": memory,
            "approval_rules": [clean_text(item, 80) for item in approvals],
            "security": {"sandbox": True, "shell": False, "root": False, "secret_access": False, "docker_access": False},
        }

    def list(self, actor: str, workspace_id: str) -> list[dict[str, Any]]:
        self.security.authorize(actor, workspace_id, permission="tasks:read")
        with self.database._connect() as connection:
            values = connection.execute("SELECT id,name,role,goal,status,current_version,created_at,updated_at FROM agents WHERE workspace_id=? ORDER BY name", (workspace_id,)).fetchall()
        return [row(value) for value in values]

    def get(self, actor: str, workspace_id: str, agent_id: str) -> dict[str, Any] | None:
        self.security.authorize(actor, workspace_id, permission="tasks:read")
        with self.database._connect() as connection:
            value = connection.execute("SELECT a.*,v.manifest,v.checksum FROM agents a JOIN agent_versions v ON v.workspace_id=a.workspace_id AND v.agent_id=a.id AND v.version=a.current_version WHERE a.workspace_id=? AND a.id=?", (workspace_id, agent_id)).fetchone()
        if value is None:
            return None
        result = row(value)
        result["manifest"] = json.loads(result["manifest"])
        result.pop("owner_id", None)
        return result
