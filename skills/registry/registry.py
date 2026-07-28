from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nexora.skills.validators import SkillManifestValidator, SkillValidationError


BUILTIN_SKILLS = (
    "content-writer",
    "research",
    "github-assistant",
    "github-agent",
    "analytics",
    "secure-code-review",
    "runtime-testing-patterns",
    "e2e-testing-patterns",
    "technical-documentation",
    "diagram-maker",
    "markdown-authoring",
    "project-documentation",
    "api-design-review",
    "python-quality",
    "threat-modeling",
    "database-design-review",
    "architecture-review",
    "accessibility-review",
)
SKILL_STATES = {"DISCOVERED", "VALIDATED", "INSTALLED", "ACTIVE", "DISABLED", "FAILED", "REMOVED"}


class SkillRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class SkillManifest:
    id: str
    name: str
    version: str
    description: str
    author: str
    category: str
    agent: str
    permissions: dict[str, Any]
    risk: str
    tools: tuple[str, ...]
    sandbox_enabled: bool
    approval_required: bool
    default_status: str
    manifest_hash: str
    source: Path


class SkillRegistry:
    """Registry for reviewed local manifests with persistent lifecycle state."""

    def __init__(
        self,
        manifests_root: Path,
        *,
        database: Any,
        audit: Any | None = None,
        agent_registry: Any | None = None,
        platform_version: str = "1.8.0",
    ) -> None:
        self.manifests_root = Path(manifests_root).resolve()
        self.database = database
        self.audit = audit
        self.agent_registry = agent_registry
        self.validator = SkillManifestValidator(
            self.manifests_root / "skill.schema.json",
            platform_version=platform_version,
        )
        self._skills: dict[str, SkillManifest] = {}

    def load(self) -> "SkillRegistry":
        loaded: dict[str, SkillManifest] = {}
        for skill_id in BUILTIN_SKILLS:
            manifest = self._read(skill_id)
            created = self.database.register_skill(manifest, initial_status=manifest.default_status)
            if created:
                for state in ("DISCOVERED", "VALIDATED", "INSTALLED", manifest.default_status):
                    self._transition(manifest.id, state, "SUCCESS")
            else:
                self.database.replace_skill_permissions(manifest.id, self._permission_rows(manifest))
            loaded[manifest.id] = manifest
        self._skills = loaded
        return self

    def register(self, skill_id: str) -> SkillManifest:
        manifest = self._read(skill_id)
        created = self.database.register_skill(manifest, initial_status="DISABLED")
        if created:
            for state in ("DISCOVERED", "VALIDATED", "INSTALLED", "DISABLED"):
                self._transition(manifest.id, state, "SUCCESS")
        self._skills[manifest.id] = manifest
        return manifest

    def enable(self, skill_id: str, *, approval_id: str) -> dict[str, Any]:
        manifest = self.require(skill_id)
        self.database.set_skill_status(manifest.id, "ACTIVE")
        self._transition(manifest.id, "ACTIVE", "SUCCESS", approval_id=approval_id)
        return self.info(manifest.id)

    def disable(self, skill_id: str, *, approval_id: str) -> dict[str, Any]:
        manifest = self.require(skill_id)
        self.database.set_skill_status(manifest.id, "DISABLED")
        self._transition(manifest.id, "DISABLED", "SUCCESS", approval_id=approval_id)
        return self.info(manifest.id)

    def reload(self, skill_id: str, *, approval_id: str) -> dict[str, Any]:
        previous = self.require(skill_id)
        current = self._read(skill_id)
        if current.id != previous.id:
            raise SkillRegistryError("skill id mismatch")
        self.database.update_skill_manifest(current)
        self.database.replace_skill_permissions(current.id, self._permission_rows(current))
        self._skills[current.id] = current
        self._transition(current.id, "VALIDATED", "SUCCESS", approval_id=approval_id)
        return self.info(current.id)

    def remove(self, skill_id: str, *, approval_id: str = "registry") -> None:
        manifest = self.require(skill_id)
        self.database.set_skill_status(manifest.id, "REMOVED")
        self._transition(manifest.id, "REMOVED", "SUCCESS", approval_id=approval_id)
        self._skills.pop(manifest.id, None)

    def get(self, skill_id: str) -> SkillManifest | None:
        return self._skills.get(str(skill_id).strip().casefold())

    def require(self, skill_id: str) -> SkillManifest:
        manifest = self.get(skill_id)
        if manifest is None:
            raise SkillRegistryError("unknown skill")
        return manifest

    def require_active(self, skill_id: str) -> SkillManifest:
        manifest = self.require(skill_id)
        if self.database.get_skill_status(manifest.id) != "ACTIVE":
            raise SkillRegistryError("skill is not active")
        return manifest

    def all(self) -> tuple[SkillManifest, ...]:
        return tuple(self._skills[key] for key in BUILTIN_SKILLS if key in self._skills)

    def list(self) -> list[dict[str, Any]]:
        return [self.info(manifest.id) for manifest in self.all()]

    def info(self, skill_id: str) -> dict[str, Any]:
        manifest = self.require(skill_id)
        status = self.database.get_skill_status(manifest.id) or "FAILED"
        return {
            "id": manifest.id,
            "name": manifest.name,
            "version": manifest.version,
            "description": manifest.description,
            "author": manifest.author,
            "category": manifest.category,
            "agent": manifest.agent,
            "permissions": json.loads(json.dumps(manifest.permissions)),
            "risk": manifest.risk.upper(),
            "tools": list(manifest.tools),
            "sandbox": manifest.sandbox_enabled,
            "approval_required": manifest.approval_required,
            "status": status,
        }

    def health(self) -> dict[str, int | bool]:
        states = [self.database.get_skill_status(item.id) for item in self.all()]
        return {
            "ok": len(states) == len(BUILTIN_SKILLS) and all(state in {"ACTIVE", "DISABLED"} for state in states),
            "loaded": len(states),
            "active": sum(1 for state in states if state == "ACTIVE"),
        }

    def _read(self, skill_id: str) -> SkillManifest:
        normalized = str(skill_id).strip().casefold()
        if normalized not in BUILTIN_SKILLS:
            raise SkillRegistryError("unknown skill")
        path = self.manifests_root / f"{normalized}.yaml"
        try:
            raw = self.validator.validate_file(path)
        except SkillValidationError:
            if self.database.skill_exists(normalized):
                self.database.set_skill_status(normalized, "FAILED")
                self._transition(normalized, "FAILED", "SKILL_VALIDATION_FAILED")
            raise
        if str(raw["id"]) != normalized:
            raise SkillRegistryError("skill id mismatch")
        if self.agent_registry is not None and self.agent_registry.get(str(raw["agent"])) is None:
            raise SkillRegistryError("unknown skill agent")
        canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return SkillManifest(
            id=normalized,
            name=str(raw["name"]),
            version=str(raw["version"]),
            description=str(raw["description"]),
            author=str(raw["author"]),
            category=str(raw["category"]),
            agent=str(raw["agent"]),
            permissions=dict(raw["permissions"]),
            risk=str(raw["risk"]["level"]),
            tools=tuple(str(item) for item in raw["tools"]),
            sandbox_enabled=bool(raw["security"]["sandbox"]["enabled"]),
            approval_required=bool(raw["approval"]["required"]),
            default_status=str(raw["status"]),
            manifest_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            source=path,
        )

    def _transition(self, skill_id: str, event: str, result: str, **metadata: Any) -> None:
        if event not in SKILL_STATES:
            raise SkillRegistryError("invalid lifecycle state")
        self.database.insert_skill_event(skill_id, event, result)
        if self.audit is not None:
            audit_event = {
                "DISCOVERED": "SKILL_REGISTERED",
                "VALIDATED": "SKILL_VALIDATED",
                "INSTALLED": "SKILL_REGISTERED",
                "ACTIVE": "SKILL_ENABLED",
                "DISABLED": "SKILL_DISABLED",
                "FAILED": "SKILL_FAILED",
                "REMOVED": "SKILL_REMOVED",
            }[event]
            self.audit.record(
                audit_event,
                source="skill_registry",
                action_result=result,
                skill_id=skill_id,
                lifecycle=event,
                **metadata,
            )

    @staticmethod
    def _permission_rows(manifest: SkillManifest) -> list[tuple[str, str]]:
        rows = [("filesystem", f"{scope}:{manifest.permissions['filesystem']['mode']}") for scope in manifest.permissions["filesystem"]["scope"]]
        rows.append(("network", str(manifest.permissions["network"]["mode"])))
        rows.append(("shell", "disabled"))
        rows.append(("production", "disabled"))
        return rows
