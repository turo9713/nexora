from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .validator import TemplateValidationError, TemplateValidator


BUILTIN_TEMPLATES = (
    "content-factory",
    "code-review",
    "research-agent",
    "analytics-report",
    "telegram-assistant",
)
TEMPLATE_STATES = {"DISCOVERED", "VALIDATED", "ACTIVE", "DISABLED", "FAILED"}


class TemplateRegistryError(RuntimeError):
    pass


class TemplateApprovalRequired(TemplateRegistryError):
    pass


@dataclass(frozen=True)
class TemplateManifest:
    id: str
    name: str
    version: str
    description: str
    agents: tuple[str, ...]
    skills: tuple[str, ...]
    permissions: dict[str, Any]
    approval_required: bool
    created_by: str
    default_status: str
    manifest_hash: str
    source: Path

    @property
    def risk(self) -> str:
        return str(self.permissions["level"]).upper()


class TemplateRegistry:
    """Registry for reviewed, declarative workflows; templates never execute code."""

    def __init__(self, root: Path, *, database: Any, agents: Any, skills: Any, policy: Any, audit: Any | None = None, metrics: Any | None = None) -> None:
        self.root = Path(root).resolve()
        self.database = database
        self.agents = agents
        self.skills = skills
        self.policy = policy
        self.audit = audit
        self.metrics = metrics
        self.validator = TemplateValidator(self.root / "template.schema.json")
        self._templates: dict[str, TemplateManifest] = {}

    def load(self) -> "TemplateRegistry":
        loaded: dict[str, TemplateManifest] = {}
        for template_id in BUILTIN_TEMPLATES:
            manifest = self._read(template_id)
            created = self.database.register_template(manifest, initial_status=manifest.default_status)
            if created:
                for state in ("DISCOVERED", "VALIDATED", manifest.default_status):
                    self._transition(manifest.id, state, "SUCCESS")
            loaded[manifest.id] = manifest
        self._templates = loaded
        return self

    def register(self, template_id: str) -> TemplateManifest:
        manifest = self._read(template_id)
        created = self.database.register_template(manifest, initial_status="DISABLED")
        if created:
            for state in ("DISCOVERED", "VALIDATED", "DISABLED"):
                self._transition(manifest.id, state, "SUCCESS")
        self._templates[manifest.id] = manifest
        return manifest

    def get(self, template_id: str) -> TemplateManifest | None:
        return self._templates.get(str(template_id).casefold().strip())

    def require(self, template_id: str) -> TemplateManifest:
        value = self.get(template_id)
        if value is None:
            raise TemplateRegistryError("unknown template")
        return value

    def list(self) -> list[dict[str, Any]]:
        return [self.info(template_id) for template_id in BUILTIN_TEMPLATES if template_id in self._templates]

    def info(self, template_id: str) -> dict[str, Any]:
        item = self.require(template_id)
        return {
            "id": item.id,
            "name": item.name,
            "version": item.version,
            "description": item.description,
            "agents": list(item.agents),
            "skills": list(item.skills),
            "permissions": json.loads(json.dumps(item.permissions)),
            "risk": item.risk,
            "approval_required": item.approval_required,
            "created_by": item.created_by,
            "status": self.database.get_template_status(item.id) or "FAILED",
        }

    def enable(self, template_id: str, *, approval_id: str) -> dict[str, Any]:
        item = self.require(template_id)
        self.database.set_template_status(item.id, "ACTIVE")
        self._transition(item.id, "ACTIVE", "SUCCESS", approval_id=approval_id)
        return self.info(item.id)

    def disable(self, template_id: str, *, approval_id: str) -> dict[str, Any]:
        item = self.require(template_id)
        self.database.set_template_status(item.id, "DISABLED")
        self._transition(item.id, "DISABLED", "SUCCESS", approval_id=approval_id)
        return self.info(item.id)

    def install(self, owner: str, template_id: str, *, approval_id: str | None = None) -> dict[str, Any]:
        item = self.require(template_id)
        if self.database.get_template_status(item.id) != "ACTIVE":
            raise TemplateRegistryError("template is not active")
        existing = self.database.get_template_installation(owner, item.id)
        if existing is not None and existing["status"] == "ACTIVE":
            return existing
        for agent_id in item.agents:
            decision = self.policy.evaluate(agent_id, risk=item.risk, approval_granted=bool(approval_id))
            if not decision.allowed:
                if decision.requires_approval:
                    raise TemplateApprovalRequired("template approval required")
                raise TemplateRegistryError("template denied by policy")
        if item.approval_required and not approval_id:
            raise TemplateApprovalRequired("template approval required")
        record = self.database.install_template(owner, item.id, approval_id=approval_id)
        if self.audit is not None:
            self.audit.record("TEMPLATE_INSTALLED", source="template_registry", action_result="SUCCESS", template_id=item.id)
        if self.metrics is not None:
            self.metrics.template_installed(owner, item.id)
        return record

    def rollback_installation(self, owner: str, template_id: str, *, approval_id: str) -> dict[str, Any]:
        record = self.database.rollback_template_installation(owner, template_id, approval_id)
        if self.audit is not None:
            self.audit.record("TEMPLATE_ROLLED_BACK", source="template_registry", action_result="SUCCESS", template_id=template_id)
        return record

    def health(self) -> dict[str, int | bool]:
        states = [self.database.get_template_status(item) for item in BUILTIN_TEMPLATES]
        return {"ok": all(state in {"ACTIVE", "DISABLED"} for state in states), "loaded": len(self._templates), "active": sum(state == "ACTIVE" for state in states)}

    def _read(self, template_id: str) -> TemplateManifest:
        normalized = str(template_id).casefold().strip()
        if normalized not in BUILTIN_TEMPLATES:
            raise TemplateRegistryError("unknown template")
        path = self.root / normalized / "template.yaml"
        try:
            raw = self.validator.validate_file(path)
        except TemplateValidationError:
            if self.database.template_exists(normalized):
                self.database.set_template_status(normalized, "FAILED")
                self._transition(normalized, "FAILED", "TEMPLATE_VALIDATION_FAILED")
            raise
        if raw["id"] != normalized:
            raise TemplateRegistryError("template id mismatch")
        for agent_id in raw["agents"]:
            if self.agents.get(str(agent_id)) is None:
                raise TemplateRegistryError("unknown template agent")
        for skill_id in raw["skills"]:
            if self.skills.get(str(skill_id)) is None:
                raise TemplateRegistryError("unknown template skill")
        canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return TemplateManifest(
            id=normalized,
            name=str(raw["name"]),
            version=str(raw["version"]),
            description=str(raw["description"]),
            agents=tuple(str(value) for value in raw["agents"]),
            skills=tuple(str(value) for value in raw["skills"]),
            permissions=dict(raw["permissions"]),
            approval_required=bool(raw["approval_required"]),
            created_by=str(raw["created_by"]),
            default_status=str(raw["status"]),
            manifest_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            source=path,
        )

    def _transition(self, template_id: str, event: str, result: str, **metadata: Any) -> None:
        if event not in TEMPLATE_STATES:
            raise TemplateRegistryError("invalid template state")
        self.database.insert_template_event(template_id, event, result)
        if self.audit is not None:
            self.audit.record(f"TEMPLATE_{event}", source="template_registry", action_result=result, template_id=template_id, **metadata)
