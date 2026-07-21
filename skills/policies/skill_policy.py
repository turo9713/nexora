from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SkillPolicyDecision:
    allowed: bool
    requires_approval: bool
    reason: str


class SkillPolicyEngine:
    """Deny-by-default permission checks for declarative skill activation."""

    SCOPE_ROOTS = {"drafts": "drafts", "workspace": ".", "data": "data"}

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def evaluate(
        self,
        manifest: Any,
        *,
        agent_id: str,
        tool: str | None = None,
        path: str | Path | None = None,
        network_mode: str = "none",
    ) -> SkillPolicyDecision:
        permissions = manifest.permissions
        if str(agent_id).casefold() != manifest.agent:
            return SkillPolicyDecision(False, False, "agent_mismatch")
        if permissions["shell"]["enabled"] or permissions["production"]["enabled"]:
            return SkillPolicyDecision(False, False, "forbidden_permission")
        if not manifest.sandbox_enabled:
            return SkillPolicyDecision(False, False, "sandbox_required")
        if tool is not None and tool not in manifest.tools:
            return SkillPolicyDecision(False, False, "tool_not_allowed")
        allowed_network = permissions["network"]["mode"]
        if network_mode not in {"none", allowed_network}:
            return SkillPolicyDecision(False, False, "network_not_allowed")
        if path is not None and not self._path_allowed(path, permissions["filesystem"]):
            return SkillPolicyDecision(False, False, "path_outside_skill_scope")
        return SkillPolicyDecision(True, bool(manifest.approval_required), "allowed")

    def _path_allowed(self, path: str | Path, filesystem: dict[str, Any]) -> bool:
        candidate = Path(path)
        candidate = candidate.resolve() if candidate.is_absolute() else (self.workspace_root / candidate).resolve()
        for scope in filesystem.get("scope", []):
            relative = self.SCOPE_ROOTS.get(str(scope))
            if relative is None:
                continue
            root = (self.workspace_root / relative).resolve()
            try:
                candidate.relative_to(root)
                return True
            except ValueError:
                continue
        return False
