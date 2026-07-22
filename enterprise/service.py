from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nexora.security.audit.redaction import sanitize_metadata


POLICY_TYPES = {"AGENT_POLICY", "DATA_POLICY", "ACCESS_POLICY", "WORKFLOW_POLICY", "SECURITY_POLICY"}
POLICY_STATUSES = {"DRAFT", "ACTIVE", "DISABLED", "ARCHIVED"}
RISK_LEVELS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
FORBIDDEN_RULES = {"allow_root", "allow_secrets", "docker_access", "disable_sandbox", "bypass_approval"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EnterpriseAccessDenied(PermissionError):
    pass


class EnterpriseValidationError(ValueError):
    pass


class EnterpriseService:
    """Tenant-scoped enterprise facade. It never talks to OpenClaw or executes tools."""

    def __init__(self, database: Any, teams: Any, policy: Any, audit: Any, registry: Any | None = None, state_root: Path | None = None, backup_root: Path | None = None) -> None:
        self.database = database
        self.teams = teams
        self.policy = policy
        self.audit = audit
        self.registry = registry
        self.state_root = Path(state_root) if state_root else database.path.parent
        self.backup_root = Path(backup_root) if backup_root else self.state_root.parent / "backups"

    def security_center(self, actor: str, workspace_id: str | None = None) -> dict[str, Any]:
        scope = self._scope(actor, workspace_id, "audit:read")
        summary = self.database.enterprise_security_summary(scope["organization_id"])
        enabled = int(self.registry.health().get("enabled", 0)) if self.registry is not None else 0
        return {
            "organization_id": scope["organization_id"],
            "workspace_id": scope["workspace_id"],
            "users": summary["users"],
            "policies": summary["policies"],
            "active_agents": enabled,
            "security_events": summary["security_events"],
            "risk_level": summary["risk_level"],
        }

    def list_policies(self, actor: str, workspace_id: str | None = None) -> dict[str, Any]:
        scope = self._scope(actor, workspace_id, "audit:read")
        return {"items": self.database.list_enterprise_policies(scope["organization_id"]), "workspace_id": scope["workspace_id"]}

    def create_policy(self, actor: str, workspace_id: str, name: str, policy_type: str, rules: dict[str, Any], *, approval_id: str) -> dict[str, Any]:
        scope = self._scope(actor, workspace_id, "security:manage")
        clean_name = " ".join(str(name).split())[:120]
        normalized_type = str(policy_type).upper()
        clean_rules = self._rules(rules)
        if len(clean_name) < 3 or normalized_type not in POLICY_TYPES:
            raise EnterpriseValidationError("invalid policy")
        action = f"enterprise:policy_create:{scope['organization_id']}"
        self._approval(actor, approval_id, action)
        policy_id = "POL-" + uuid.uuid4().hex[:12].upper()
        now = utc_now()
        record = {"id": policy_id, "organization_id": scope["organization_id"], "name": clean_name, "type": normalized_type, "rules": clean_rules, "status": "ACTIVE", "current_version": 1, "created_at": now, "updated_at": now}
        self.database.create_enterprise_policy(record, approval_id, "Initial approved version")
        self._security_event(actor, scope["organization_id"], "POLICY_CREATED", policy_id, "SUCCESS", "MEDIUM")
        return self._safe_policy(record)

    def update_policy(self, actor: str, workspace_id: str, policy_id: str, rules: dict[str, Any], changelog: str, *, approval_id: str) -> dict[str, Any]:
        scope = self._scope(actor, workspace_id, "security:manage")
        current = self.database.get_enterprise_policy(scope["organization_id"], policy_id)
        if current is None:
            raise EnterpriseAccessDenied("policy unavailable")
        self._approval(actor, approval_id, f"enterprise:policy_update:{policy_id}")
        version = int(current["current_version"]) + 1
        self.database.add_policy_version(policy_id, version, self._rules(rules), self._text(changelog, 500), approval_id)
        updated = self.database.get_enterprise_policy(scope["organization_id"], policy_id)
        self._security_event(actor, scope["organization_id"], "POLICY_UPDATED", policy_id, "SUCCESS", "MEDIUM")
        return self._safe_policy(updated or current)

    def rollback_policy(self, actor: str, workspace_id: str, policy_id: str, version: int, *, approval_id: str) -> dict[str, Any]:
        scope = self._scope(actor, workspace_id, "security:manage")
        if self.database.get_enterprise_policy(scope["organization_id"], policy_id) is None:
            raise EnterpriseAccessDenied("policy unavailable")
        self._approval(actor, approval_id, f"enterprise:policy_rollback:{policy_id}")
        source = self.database.get_policy_version(policy_id, int(version))
        if source is None:
            raise EnterpriseValidationError("policy version unavailable")
        current = self.database.get_enterprise_policy(scope["organization_id"], policy_id)
        next_version = int(current["current_version"]) + 1
        self.database.add_policy_version(policy_id, next_version, source["rules"], f"Rollback to version {int(version)}", approval_id)
        updated = self.database.get_enterprise_policy(scope["organization_id"], policy_id)
        self._security_event(actor, scope["organization_id"], "POLICY_ROLLED_BACK", policy_id, "SUCCESS", "HIGH")
        return self._safe_policy(updated or current)

    def security_events(self, actor: str, workspace_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        scope = self._scope(actor, workspace_id, "audit:read")
        limit = max(1, min(200, int(limit)))
        return {"items": self.database.list_security_events(scope["organization_id"], limit), "chain_valid": self.database.validate_security_event_chain(scope["organization_id"])}

    def sla(self, actor: str, workspace_id: str | None = None) -> dict[str, Any]:
        scope = self._scope(actor, workspace_id, "tasks:read")
        return self.database.enterprise_sla(scope["organization_id"], scope["workspace_id"])

    def storage_health(self, actor: str, workspace_id: str | None = None) -> dict[str, Any]:
        scope = self._scope(actor, workspace_id, "audit:read")
        database_status = self._database_integrity()
        permissions = self._permissions_health()
        usage = shutil.disk_usage(self.database.path.parent)
        disk_percent = round((usage.used / usage.total) * 100, 1) if usage.total else 0.0
        backup_status = "OK" if self.backup_root.is_dir() and any(item.is_file() for item in self.backup_root.iterdir()) else "UNKNOWN"
        return {"database": database_status, "permissions": permissions, "backup": backup_status, "disk_percent": disk_percent, "status": "OK" if database_status == permissions == backup_status == "OK" and disk_percent < 90 else "DEGRADED", "workspace_id": scope["workspace_id"]}

    def deployment_profiles(self, actor: str, workspace_id: str | None = None) -> dict[str, Any]:
        self._scope(actor, workspace_id, "audit:read")
        return {"items": self.database.list_deployment_profiles()}

    def sso_foundation(self, actor: str, workspace_id: str | None = None) -> dict[str, Any]:
        self._scope(actor, workspace_id, "security:manage")
        return {"configured": False, "authentication_changed": False, "providers": [{"type": value, "ready": True, "enabled": False} for value in ("SAML", "OIDC", "OAUTH2")]}

    def compliance(self, actor: str, workspace_id: str | None = None) -> dict[str, Any]:
        scope = self._scope(actor, workspace_id, "audit:read")
        chain = self.database.validate_security_event_chain(scope["organization_id"])
        return {"certified": False, "foundation": True, "controls": {"deny_by_default": True, "tenant_isolation": True, "approval_required": True, "immutable_security_audit": chain, "secret_redaction": True}}

    def _scope(self, actor: str, workspace_id: str | None, permission: str) -> dict[str, Any]:
        selected = str(workspace_id or "")
        if not selected:
            workspaces = self.teams.list_workspaces(actor)
            if not workspaces:
                raise EnterpriseAccessDenied("workspace unavailable")
            selected = str(workspaces[0]["id"])
        try:
            context = self.teams.workspace_context(actor, selected, permission)
        except PermissionError as exc:
            raise EnterpriseAccessDenied("workspace unavailable") from exc
        return {**context, "workspace_id": selected}

    def _approval(self, actor: str, approval_id: str, action: str) -> None:
        if not re.fullmatch(r"APR-[A-Za-z0-9-]{6,64}", str(approval_id or "")) or not self.database.consume_team_approval(actor, approval_id, action):
            raise EnterpriseAccessDenied("approval unavailable")
        decision = self.policy.evaluate("orchestrator", risk="HIGH", action_type="configuration_changes", approval_granted=True)
        if not decision.allowed:
            raise EnterpriseAccessDenied("policy denied")

    def _security_event(self, actor: str, organization_id: str, action: str, resource: str, result: str, risk: str) -> None:
        risk = risk if risk in RISK_LEVELS else "HIGH"
        event = {"id": "SEC-" + uuid.uuid4().hex[:16].upper(), "organization_id": organization_id, "actor_hash": hashlib.sha256(str(actor).encode()).hexdigest(), "action": self._text(action, 100), "resource": self._text(resource, 120), "result": self._text(result, 80), "risk_level": risk, "created_at": utc_now()}
        self.database.append_security_event(event)
        self.audit.record(action, severity="SECURITY" if risk in {"HIGH", "CRITICAL"} else "INFO", source="enterprise", action_result=result, organization_id=organization_id, resource=resource)

    @staticmethod
    def _rules(rules: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(rules, dict) or not rules:
            raise EnterpriseValidationError("policy rules required")
        clean = sanitize_metadata(rules)
        lowered = {str(key).lower() for key in clean}
        if lowered & FORBIDDEN_RULES or clean.get("allow_shell") is True or clean.get("external_write") is True:
            raise EnterpriseValidationError("unsafe policy rule")
        return clean

    @staticmethod
    def _text(value: Any, limit: int) -> str:
        return " ".join(str(value).split())[:limit]

    @staticmethod
    def _safe_policy(value: dict[str, Any]) -> dict[str, Any]:
        return {key: value[key] for key in ("id", "organization_id", "name", "type", "rules", "status", "current_version", "created_at", "updated_at") if key in value}

    def _database_integrity(self) -> str:
        try:
            uri = f"file:{self.database.path.as_posix()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=3)
            try:
                return "OK" if str(connection.execute("PRAGMA integrity_check").fetchone()[0]).lower() == "ok" else "ERROR"
            finally:
                connection.close()
        except sqlite3.Error:
            return "ERROR"

    def _permissions_health(self) -> str:
        if os.name != "posix":
            return "OK"
        roots = [path for path in (self.state_root, self.database.path.parent) if path.exists()]
        for root in roots:
            if root.is_symlink() or stat.S_IMODE(root.stat().st_mode) & 0o077:
                return "ERROR"
            for item in root.rglob("*"):
                if item.is_symlink():
                    return "ERROR"
                mode = stat.S_IMODE(item.stat().st_mode)
                if item.is_dir() and mode & 0o077:
                    return "ERROR"
                if item.is_file() and mode & 0o077:
                    return "ERROR"
        return "OK"
