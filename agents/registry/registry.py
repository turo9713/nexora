from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


REQUIRED_AGENTS = (
    "orchestrator",
    "developer",
    "content",
    "research",
    "analytics",
    "qa",
    "devops",
    "sales",
)


class RegistryError(RuntimeError):
    """Raised when an agent manifest is missing or unsafe."""


@dataclass(frozen=True)
class AgentManifest:
    id: str
    name: str
    description: str
    system_role: str
    workspace: str
    permissions: tuple[str, ...]
    tools_allowed: tuple[str, ...]
    tools_denied: tuple[str, ...]
    approval_required: tuple[str, ...]
    restrictions: tuple[str, ...]
    risk_level: str
    enabled: bool
    source: Path


class AgentRegistry:
    """Fail-closed registry backed by the existing v1.4 agent manifests."""

    def __init__(self, agents_root: Path) -> None:
        self.agents_root = Path(agents_root).resolve()
        self._agents: dict[str, AgentManifest] = {}

    def load(self) -> "AgentRegistry":
        loaded: dict[str, AgentManifest] = {}
        for agent_id in REQUIRED_AGENTS:
            path = self.agents_root / agent_id / "agent.yaml"
            if not path.is_file() or path.is_symlink():
                raise RegistryError(f"manifest missing for agent: {agent_id}")
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise RegistryError(f"invalid manifest for agent: {agent_id}")
            manifest_id = str(raw.get("id") or raw.get("role") or "").strip().lower()
            if manifest_id != agent_id:
                raise RegistryError(f"agent id mismatch: {agent_id}")
            status = raw.get("status", {})
            enabled = bool(status.get("enabled", False)) if isinstance(status, dict) else False
            tools_allowed = self._strings(raw.get("tools_allowed"))
            tools_denied = self._strings(raw.get("tools_denied"))
            if not tools_allowed or set(tools_allowed) & set(tools_denied):
                raise RegistryError(f"unsafe tool policy for agent: {agent_id}")
            loaded[agent_id] = AgentManifest(
                id=agent_id,
                name=self._required_text(raw, "name", agent_id),
                description=self._required_text(raw, "description", agent_id),
                system_role=str(raw.get("system_role") or raw.get("role") or agent_id)[:100],
                workspace=str(raw.get("workspace") or "/workspace/nexora"),
                permissions=self._strings(raw.get("permissions")),
                tools_allowed=tools_allowed,
                tools_denied=tools_denied,
                approval_required=self._strings(raw.get("approval_required")),
                restrictions=self._strings(raw.get("restrictions")) or tools_denied,
                risk_level=str(raw.get("risk_level") or "HIGH").upper(),
                enabled=enabled,
                source=path,
            )
        self._agents = loaded
        return self

    @staticmethod
    def _strings(value: Any) -> tuple[str, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(str(item).strip() for item in value if str(item).strip())

    @staticmethod
    def _required_text(raw: dict[str, Any], key: str, agent_id: str) -> str:
        value = str(raw.get(key) or "").strip()
        if not value:
            raise RegistryError(f"{key} missing for agent: {agent_id}")
        return value[:500]

    def get(self, agent_id: str) -> AgentManifest | None:
        return self._agents.get(str(agent_id).strip().lower())

    def require(self, agent_id: str) -> AgentManifest:
        manifest = self.get(agent_id)
        if manifest is None or not manifest.enabled:
            raise RegistryError("agent is unknown or disabled")
        return manifest

    def all(self) -> tuple[AgentManifest, ...]:
        return tuple(self._agents[key] for key in REQUIRED_AGENTS if key in self._agents)

    def health(self) -> dict[str, int | bool]:
        enabled = sum(1 for manifest in self._agents.values() if manifest.enabled)
        return {"ok": enabled == len(REQUIRED_AGENTS), "loaded": len(self._agents), "enabled": enabled}
