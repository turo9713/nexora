from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any

from nexora.knowledge import KnowledgeValidationError, validate_document
from nexora.permissions import RBAC, ROLES
from nexora.security.audit.redaction import redact_text, sanitize_metadata
from nexora.integrations.telegram_runtime.services.progress_service import utc_now


class TeamAccessDenied(PermissionError):
    pass


class TeamValidationError(ValueError):
    pass


class TeamService:
    """Workspace-scoped collaboration facade; every resource access checks membership and RBAC."""

    def __init__(self, database: Any, policy: Any, audit: Any) -> None:
        self.database = database
        self.policy = policy
        self.audit = audit
        self.rbac = RBAC()

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}-{secrets.token_hex(6).upper()}"

    @staticmethod
    def _name(value: str, limit: int = 120) -> str:
        clean = " ".join(str(value).split())[:limit]
        if len(clean) < 2:
            raise TeamValidationError("invalid name")
        return clean

    @staticmethod
    def _external_from_email(email_hash: str) -> str:
        normalized = str(email_hash).casefold()
        if not re.fullmatch(r"[a-f0-9]{64}", normalized):
            raise TeamValidationError("invalid email hash")
        return "usr-" + normalized

    def create_organization(self, actor: str, name: str) -> dict[str, Any]:
        organization = self.database.create_organization(self._id("ORG"), actor, self._name(name))
        self._activity(organization["id"], None, "ORGANIZATION_CREATED", actor, organization["id"])
        self.audit.record("ORGANIZATION_CREATED", source="team_service", action_result="SUCCESS", organization_id=organization["id"])
        return organization

    def bootstrap_personal(self, actor: str) -> dict[str, Any]:
        organizations = self.list_organizations(actor)
        organization = organizations[0] if organizations else self.create_organization(actor, "Personal Organization")
        workspaces = self.list_workspaces(actor, organization["id"])
        workspace = workspaces[0] if workspaces else self.create_workspace(actor, organization["id"], "Personal Workspace", "Backward-compatible workspace for existing single-owner data")
        return {"organization": organization, "workspace": workspace}

    def list_organizations(self, actor: str) -> list[dict[str, Any]]:
        return self.database.list_organizations_for_user(actor)

    def archive_organization(self, actor: str, organization_id: str, *, approval_id: str) -> None:
        role = self.database.organization_role(actor, organization_id)
        self._require_role(role, "organization:manage")
        self._require_approval(actor, f"team:organization_archive:{organization_id}", approval_id)
        self.database.set_organization_status(organization_id, "ARCHIVED")
        self._activity(organization_id, None, "ORGANIZATION_ARCHIVED", actor, organization_id)

    def create_workspace(self, actor: str, organization_id: str, name: str, description: str = "") -> dict[str, Any]:
        role = self.database.organization_role(actor, organization_id)
        self._require_role(role, "workspace:create")
        workspace = self.database.create_workspace(self._id("WS"), organization_id, actor, self._name(name), redact_text(description, 1000), role)
        self._activity(organization_id, workspace["id"], "WORKSPACE_CREATED", actor, workspace["id"])
        return workspace

    def list_workspaces(self, actor: str, organization_id: str | None = None) -> list[dict[str, Any]]:
        return self.database.list_workspaces_for_user(actor, organization_id)

    def list_members(self, actor: str, workspace_id: str) -> list[dict[str, Any]]:
        self._require(actor, workspace_id, "tasks:read")
        return self.database.list_workspace_members(workspace_id)

    def invite(self, actor: str, workspace_id: str, email_hash: str, display_name: str, role: str, *, approval_id: str) -> dict[str, Any]:
        membership = self._require(actor, workspace_id, "members:manage")
        target_role = str(role).upper()
        if target_role not in ROLES or not self.rbac.can_assign(membership["role"], target_role):
            raise TeamAccessDenied("role escalation denied")
        self._require_approval(actor, f"team:workspace_invite:{workspace_id}", approval_id)
        external_hash = self._external_from_email(email_hash)
        user_id = self.database.ensure_team_user(external_hash, email_hash=email_hash.casefold(), display_name=self._name(display_name, 80))
        member = self.database.upsert_workspace_member(self._id("MEM"), workspace_id, user_id, target_role)
        self._activity(membership["organization_id"], workspace_id, "USER_JOINED", actor, member["id"], {"role": target_role})
        self.audit.record("USER_JOINED", source="team_service", action_result="SUCCESS", workspace_id=workspace_id, member_id=member["id"], role=target_role)
        return {key: member[key] for key in ("id", "workspace_id", "role", "status", "created_at")}

    def change_role(self, actor: str, workspace_id: str, user_id: int, role: str, *, approval_id: str) -> None:
        membership = self._require(actor, workspace_id, "members:manage")
        target = str(role).upper()
        if not self.rbac.can_assign(membership["role"], target):
            raise TeamAccessDenied("role escalation denied")
        self._require_approval(actor, f"team:workspace_role_change:{workspace_id}", approval_id)
        self.database.set_workspace_member(workspace_id, int(user_id), role=target)
        self._activity(membership["organization_id"], workspace_id, "MEMBER_ROLE_CHANGED", actor, str(user_id), {"role": target})

    def remove_member(self, actor: str, workspace_id: str, user_id: int, *, approval_id: str) -> None:
        membership = self._require(actor, workspace_id, "members:manage")
        self._require_approval(actor, f"team:workspace_member_remove:{workspace_id}", approval_id)
        self.database.set_workspace_member(workspace_id, int(user_id), status="REMOVED")
        self._activity(membership["organization_id"], workspace_id, "MEMBER_REMOVED", actor, str(user_id))

    def assign_component(self, actor: str, workspace_id: str, component_type: str, component_id: str, *, approval_id: str) -> None:
        membership = self._require(actor, workspace_id, f"{component_type}s:manage")
        self._require_approval(actor, f"team:workspace_component_change:{workspace_id}", approval_id)
        self.database.set_workspace_component(workspace_id, component_type, component_id, True)
        self._activity(membership["organization_id"], workspace_id, f"{component_type.upper()}_ASSIGNED", actor, component_id)

    def components(self, actor: str, workspace_id: str, component_type: str) -> list[str]:
        self._require(actor, workspace_id, "tasks:read")
        return self.database.list_workspace_components(workspace_id, component_type)

    def workspace_context(self, actor: str, workspace_id: str, permission: str = "tasks:read") -> dict[str, Any]:
        membership = self._require(actor, workspace_id, permission)
        return {key: membership[key] for key in ("organization_id", "user_id", "role")}

    def add_knowledge(self, actor: str, workspace_id: str, value: dict[str, Any]) -> dict[str, Any]:
        membership = self._require(actor, workspace_id, "knowledge:write")
        try:
            name, kind, content, access = validate_document(value.get("name", ""), value.get("type", ""), value.get("content", ""), value.get("access_level", "TEAM"))
        except KnowledgeValidationError as exc:
            raise TeamValidationError(str(exc)) from exc
        document = {"id": self._id("DOC"), "workspace_id": workspace_id, "name": name, "type": kind, "access_level": access, "content": content, "content_hash": hashlib.sha256(content.encode()).hexdigest(), "created_by": membership["user_id"], "created_at": utc_now()}
        self.database.add_knowledge_document(document)
        self._activity(membership["organization_id"], workspace_id, "KNOWLEDGE_ADDED", actor, document["id"], {"access_level": access})
        return {key: document[key] for key in ("id", "workspace_id", "name", "type", "access_level", "content_hash", "created_at")}

    def list_knowledge(self, actor: str, workspace_id: str) -> list[dict[str, Any]]:
        membership = self._require(actor, workspace_id, "knowledge:read")
        levels = ("TEAM", "MANAGERS", "ADMINS") if membership["role"] in {"OWNER", "ADMIN"} else (("TEAM", "MANAGERS") if membership["role"] == "MANAGER" else ("TEAM",))
        return self.database.list_knowledge_documents(workspace_id, levels)

    def link_task(self, actor: str, workspace_id: str, task_id: str, assignee_id: int | None = None) -> None:
        membership = self._require(actor, workspace_id, "tasks:create")
        self.database.attach_task_workspace(task_id, membership["organization_id"], workspace_id, membership["user_id"], assignee_id)
        self._activity(membership["organization_id"], workspace_id, "TASK_CREATED", actor, task_id)

    def authorize_task(self, actor: str, workspace_id: str, agent_id: str, skill_id: str) -> None:
        self._require(actor, workspace_id, "tasks:create")
        agents = set(self.database.list_workspace_components(workspace_id, "agent"))
        skills = set(self.database.list_workspace_components(workspace_id, "skill"))
        if agent_id not in agents or skill_id not in skills:
            self._denied(workspace_id, "tasks:create", "workspace_component_denied")

    def add_comment(self, actor: str, workspace_id: str, task_id: str, message: str) -> dict[str, Any]:
        membership = self._require(actor, workspace_id, "comments:create")
        if self.database.get_team_task(workspace_id, task_id) is None:
            raise TeamAccessDenied("task unavailable")
        clean = redact_text(message, 2000).strip()
        if not clean:
            raise TeamValidationError("empty comment")
        comment = {"id": self._id("CMT"), "task_id": task_id, "workspace_id": workspace_id, "author_id": membership["user_id"], "message": clean, "created_at": utc_now()}
        self.database.add_task_comment(comment)
        self._activity(membership["organization_id"], workspace_id, "COMMENT_ADDED", actor, comment["id"], {"task_id": task_id})
        return {key: comment[key] for key in ("id", "task_id", "workspace_id", "message", "created_at")}

    def list_tasks(self, actor: str, workspace_id: str, limit: int = 100) -> list[dict[str, Any]]:
        self._require(actor, workspace_id, "tasks:read")
        return self.database.list_team_tasks(workspace_id, limit)

    def comments(self, actor: str, workspace_id: str, task_id: str) -> list[dict[str, Any]]:
        self._require(actor, workspace_id, "tasks:read")
        if self.database.get_team_task(workspace_id, task_id) is None:
            raise TeamAccessDenied("task unavailable")
        return self.database.list_task_comments(workspace_id, task_id)

    def activity(self, actor: str, workspace_id: str, limit: int = 100) -> list[dict[str, Any]]:
        self._require(actor, workspace_id, "audit:read")
        return self.database.list_activity(workspace_id, limit)

    def _require(self, actor: str, workspace_id: str, permission: str) -> dict[str, Any]:
        membership = self.database.membership(actor, workspace_id)
        if membership is None or membership["workspace_status"] != "ACTIVE" or membership["organization_status"] != "ACTIVE":
            self._denied(workspace_id, permission, "membership_or_tenant_denied")
        assert membership is not None
        self._require_role(membership["role"], permission, workspace_id)
        return membership

    def _require_role(self, role: str | None, permission: str, workspace_id: str | None = None) -> None:
        decision = self.rbac.evaluate(role, permission)
        if not decision.allowed:
            self._denied(workspace_id, permission, decision.reason)

    def _require_approval(self, actor: str, action_type: str, approval_id: str) -> None:
        if not re.fullmatch(r"APR-[A-Za-z0-9-]{6,64}", str(approval_id or "")):
            raise TeamAccessDenied("approval required")
        if not self.database.consume_team_approval(actor, approval_id, action_type):
            raise TeamAccessDenied("approval unavailable")
        decision = self.policy.evaluate("orchestrator", risk="HIGH", action_type="configuration_changes", approval_granted=True)
        if not decision.allowed:
            raise TeamAccessDenied("policy denied")

    def _denied(self, workspace_id: str | None, permission: str, reason: str) -> None:
        self.audit.record("SECURITY_DENIED", severity="SECURITY", source="team_service", action_result="BLOCKED", workspace_id=workspace_id, permission=permission, reason=reason)
        raise TeamAccessDenied("resource not found or unavailable")

    def _activity(self, organization_id: str, workspace_id: str | None, event: str, actor: str, resource_id: str, payload: dict[str, Any] | None = None) -> None:
        actor_id = self.database.user_id(actor)
        self.database.add_activity({"id": self._id("EVT"), "organization_id": organization_id, "workspace_id": workspace_id, "event": event, "actor_id": actor_id, "resource_id": resource_id, "payload": sanitize_metadata(payload or {}), "created_at": utc_now()})
