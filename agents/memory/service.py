from __future__ import annotations

import hashlib
import base64
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from nexora.agents.ecosystem_common import AgentEcosystemError, clean_text, identifier, row, utc_now


class AgentMemory:
    """Workspace-bound memory with explicit PERSONAL/WORKSPACE/AGENT scopes."""

    def __init__(self, database: Any, security: Any, audit: Any, pepper: bytes) -> None:
        if len(pepper) < 32:
            raise AgentEcosystemError("AGENT_MEMORY_KEY_INVALID")
        self.database, self.security, self.audit, self.pepper = database, security, audit, pepper
        self.cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(pepper + b"nexora-agent-memory-v2").digest()))

    def put(self, actor: str, workspace_id: str, key: str, value: str, *, scope: str, agent_id: str | None = None) -> dict[str, Any]:
        scope = str(scope).upper()
        context = self.security.authorize(actor, workspace_id, permission="knowledge:write", memory_scope=scope)
        if scope == "AGENT" and not agent_id:
            raise AgentEcosystemError("AGENT_MEMORY_AGENT_REQUIRED")
        if scope != "AGENT":
            agent_id = None
        key_hash = hashlib.sha256(self.pepper + clean_text(key, 128).encode()).hexdigest()
        clean = clean_text(value, 4000)
        encrypted = self.cipher.encrypt(clean.encode("utf-8")).decode("ascii")
        now, memory_id = utc_now(), identifier("MEM")
        with self.database._connect() as connection:
            connection.execute("INSERT INTO agent_memory(id,workspace_id,owner_id,agent_id,scope,key_hash,value,classification,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'INTERNAL',?,?) ON CONFLICT(workspace_id,owner_id,agent_id,scope,key_hash) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                               (memory_id, workspace_id, context["user_id"], agent_id, scope, key_hash, encrypted, now, now))
            stored = connection.execute("SELECT id,scope,agent_id,value,classification,created_at,updated_at FROM agent_memory WHERE workspace_id=? AND owner_id=? AND agent_id IS ? AND scope=? AND key_hash=?", (workspace_id, context["user_id"], agent_id, scope, key_hash)).fetchone()
        self.database._secure_database()
        self.audit.record("AGENT_MEMORY_UPDATED", source="agent_memory", action_result="SUCCESS", workspace_id=workspace_id, memory_scope=scope, agent_id=agent_id)
        return self._decrypt(row(stored))

    def list(self, actor: str, workspace_id: str, *, scope: str, agent_id: str | None = None) -> list[dict[str, Any]]:
        scope = str(scope).upper()
        context = self.security.authorize(actor, workspace_id, permission="knowledge:read", memory_scope=scope)
        if scope != "AGENT": agent_id = None
        with self.database._connect() as connection:
            values = connection.execute("SELECT id,scope,agent_id,value,classification,created_at,updated_at FROM agent_memory WHERE workspace_id=? AND owner_id=? AND agent_id IS ? AND scope=? ORDER BY updated_at DESC", (workspace_id, context["user_id"], agent_id, scope)).fetchall()
        return [self._decrypt(row(value)) for value in values]

    def _decrypt(self, value: dict[str, Any]) -> dict[str, Any]:
        try:
            value["value"] = self.cipher.decrypt(str(value["value"]).encode("ascii"), ttl=None).decode("utf-8")
        except (InvalidToken, UnicodeError, KeyError) as exc:
            raise AgentEcosystemError("AGENT_MEMORY_DECRYPT_FAILED") from exc
        return value
