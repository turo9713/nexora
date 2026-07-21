from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from typing import Any

from nexora.marketplace.validation import PackageValidationError, PackageValidator
from nexora.security.audit.redaction import redact_text, sanitize_metadata
from nexora.integrations.telegram_runtime.services.progress_service import utc_now


class MarketplaceError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class MarketplaceService:
    """Declarative marketplace facade with tenant checks and fail-closed installation."""

    def __init__(self, database: Any, teams: Any, policy: Any, audit: Any, validator: PackageValidator | None = None) -> None:
        self.database = database
        self.teams = teams
        self.policy = policy
        self.audit = audit
        self.validator = validator or PackageValidator()

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}-{secrets.token_hex(6).upper()}"

    def register_publisher(self, actor: str, display_name: str) -> dict[str, Any]:
        name = " ".join(str(display_name).split())[:100]
        if len(name) < 2:
            raise MarketplaceError("PUBLISHER_INVALID")
        value = {"id": self._id("PUB"), "owner": actor, "display_name": name, "status": "PENDING", "created_at": utc_now(), "updated_at": utc_now()}
        try:
            result = self.database.create_publisher(value)
        except sqlite3.IntegrityError as exc:
            raise MarketplaceError("PUBLISHER_ALREADY_EXISTS") from exc
        self._event("PUBLISHER_REGISTERED", "PENDING", publisher_id=value["id"])
        return self._safe_publisher(result)

    def verify_publisher(self, actor: str, publisher_id: str, approval_id: str) -> dict[str, Any]:
        publisher = self.database.get_publisher(publisher_id)
        if publisher is None:
            raise MarketplaceError("PUBLISHER_NOT_FOUND")
        self._consume_approval(actor, approval_id, f"marketplace:publisher_verify:{publisher_id}")
        self.database.set_publisher_status(publisher_id, "VERIFIED")
        self._event("PUBLISHER_VERIFIED", "SUCCESS", publisher_id=publisher_id)
        return self._safe_publisher(self.database.get_publisher(publisher_id) or {})

    def publish(self, actor: str, publisher_id: str, manifest: dict[str, Any], signature: str | None = None) -> dict[str, Any]:
        publisher = self.database.get_publisher(publisher_id)
        if publisher is None or publisher.get("owner") != actor or publisher.get("status") != "VERIFIED":
            self._denied("MARKETPLACE_PUBLISH_DENIED", publisher_id=publisher_id)
        try:
            result = self.validator.validate(manifest, signature)
        except PackageValidationError as exc:
            self._event("PACKAGE_REJECTED", str(exc), publisher_id=publisher_id)
            self.audit.record("MARKETPLACE_VALIDATION_FAILED", severity="SECURITY", source="marketplace", action_result="REJECTED", reason=str(exc))
            raise MarketplaceError(str(exc)) from exc
        policy = self.policy.evaluate("orchestrator", risk="LOW", action_type="marketplace_publish")
        if not policy.allowed:
            self._denied("MARKETPLACE_POLICY_DENIED", reason=policy.reason)
        item_id = str(result.manifest["id"])
        existing_item = self.database.get_marketplace_item(item_id)
        if existing_item is not None and existing_item.get("author_id") != publisher_id:
            raise MarketplaceError("MARKETPLACE_ITEM_EXISTS")
        if existing_item is not None and self.database.get_marketplace_package(item_id, result.manifest["version"]) is not None:
            raise MarketplaceError("MARKETPLACE_VERSION_EXISTS")
        if existing_item is not None and self._version(result.manifest["version"]) <= self._version(str(existing_item["version"])):
            raise MarketplaceError("MARKETPLACE_VERSION_NOT_NEWER")
        now = utc_now()
        item = {
            "id": item_id,
            "type": result.manifest["type"],
            "name": redact_text(result.manifest["name"], 120),
            "description": redact_text(result.manifest["description"], 1000),
            "current_version": result.manifest["version"],
            "author_id": publisher_id,
            "category": re.sub(r"[^a-z0-9-]", "", str(result.manifest.get("category") or result.manifest["type"]).casefold())[:64] or "other",
            "risk_level": result.manifest["risk_level"],
            "status": "PUBLISHED",
            "created_at": now,
            "updated_at": now,
        }
        package = {
            "id": self._id("PKG"), "item_id": item_id, "version": result.manifest["version"],
            "manifest": result.canonical, "checksum": result.checksum, "signature": signature,
            "signature_status": result.signature_status, "validation_status": "APPROVED", "created_at": now,
        }
        try:
            if existing_item is None:
                self.database.insert_marketplace_item(item, package)
            else:
                self.database.add_marketplace_package_version(item, package)
        except sqlite3.IntegrityError as exc:
            raise MarketplaceError("MARKETPLACE_PACKAGE_CONFLICT") from exc
        for event in ("PACKAGE_SUBMITTED", "PACKAGE_VALIDATED", "PACKAGE_PUBLISHED"):
            self._event(event, "SUCCESS", item_id=item_id, publisher_id=publisher_id, metadata={"version": package["version"], "checksum": package["checksum"]})
        self.audit.record("MARKETPLACE_PACKAGE_PUBLISHED", source="marketplace", action_result="SUCCESS", item_id=item_id, item_type=item["type"], risk=item["risk_level"])
        return self.item(item_id, include_manifest=True)

    def catalog(self, *, search: str | None = None, category: str | None = None, item_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return [self._safe_item(value) for value in self.database.list_marketplace_items(search=search, category=category, item_type=item_type, limit=limit)]

    def item(self, item_id: str, *, include_manifest: bool = False) -> dict[str, Any]:
        item = self.database.get_marketplace_item(item_id)
        if item is None or item.get("status") not in {"PUBLISHED", "DISABLED"}:
            raise MarketplaceError("MARKETPLACE_ITEM_NOT_FOUND")
        result = self._safe_item(item)
        package = self.database.get_marketplace_package(item_id)
        if package is None:
            raise MarketplaceError("MARKETPLACE_PACKAGE_MISSING")
        result.update(checksum=package["checksum"], signature_status=package["signature_status"], validation_status=package["validation_status"], versions=self.database.list_marketplace_versions(item_id), reviews=self.database.list_marketplace_reviews(item_id))
        if include_manifest:
            result["manifest"] = json.loads(package["manifest"])
        return result

    def install(self, actor: str, workspace_id: str, item_id: str, *, version: str | None = None, approval_id: str | None = None) -> dict[str, Any]:
        context = self._workspace(actor, workspace_id, "skills:manage")
        item = self.database.get_marketplace_item(item_id)
        package = self.database.get_marketplace_package(item_id, version)
        if item is None or item.get("status") != "PUBLISHED" or package is None or package.get("validation_status") != "APPROVED":
            raise MarketplaceError("MARKETPLACE_ITEM_NOT_FOUND")
        try:
            validated = self.validator.validate(json.loads(package["manifest"]), package.get("signature"))
        except (ValueError, TypeError, PackageValidationError) as exc:
            self._denied("MARKETPLACE_PACKAGE_TAMPERED", item_id=item_id)
            raise MarketplaceError("MARKETPLACE_PACKAGE_TAMPERED") from exc
        if not secrets.compare_digest(validated.checksum, str(package["checksum"])):
            self._denied("MARKETPLACE_PACKAGE_TAMPERED", item_id=item_id)
        requires_approval = str(item["risk_level"]) in {"MEDIUM", "HIGH"} or str(item["type"]) == "INTEGRATION"
        action_type = f"marketplace:install:{workspace_id}:{item_id}:{package['version']}"
        if requires_approval:
            self._consume_approval(actor, approval_id or "", action_type)
        decision = self.policy.evaluate("orchestrator", risk=item["risk_level"], action_type="configuration_changes" if requires_approval else None, approval_granted=requires_approval)
        if not decision.allowed:
            self._denied("MARKETPLACE_POLICY_DENIED", item_id=item_id, reason=decision.reason)
        existing = self.database.get_marketplace_installation(workspace_id, item_id, package["version"])
        if existing is not None:
            if existing["status"] == "ACTIVE":
                return existing
            raise MarketplaceError("MARKETPLACE_INSTALLATION_EXISTS")
        now = utc_now()
        installation = self.database.add_marketplace_installation({
            "id": self._id("INS"), "workspace_id": workspace_id, "item_id": item_id, "package_id": package["id"],
            "version": package["version"], "installed_by": context["user_id"], "status": "ACTIVE",
            "approval_id": approval_id, "created_at": now, "updated_at": now,
        })
        self.database.add_marketplace_license({"id": self._id("LIC"), "item_id": item_id, "package_id": package["id"], "owner": workspace_id, "type": "COMMUNITY", "status": "ACTIVE", "created_at": now})
        self._event("PACKAGE_INSTALLED", "SUCCESS", item_id=item_id, metadata={"workspace_id": workspace_id, "version": package["version"]})
        self.audit.record("MARKETPLACE_PACKAGE_INSTALLED", source="marketplace", action_result="SUCCESS", workspace_id=workspace_id, item_id=item_id)
        return installation

    def rollback_installation(self, actor: str, workspace_id: str, item_id: str, version: str, *, approval_id: str) -> bool:
        self._workspace(actor, workspace_id, "skills:manage")
        self._consume_approval(actor, approval_id, f"marketplace:rollback:{workspace_id}:{item_id}:{version}")
        changed = self.database.rollback_marketplace_installation(workspace_id, item_id, version)
        self._event("PACKAGE_ROLLED_BACK", "SUCCESS" if changed else "NOT_FOUND", item_id=item_id, metadata={"workspace_id": workspace_id, "version": version})
        return changed

    def review(self, actor: str, workspace_id: str, item_id: str, rating: int, comment: str) -> dict[str, Any]:
        context = self._workspace(actor, workspace_id, "tasks:read")
        package = self.database.get_marketplace_package(item_id)
        installation = None if package is None else self.database.get_marketplace_installation(workspace_id, item_id, package["version"])
        if package is None or installation is None or installation.get("status") != "ACTIVE":
            raise MarketplaceError("MARKETPLACE_REVIEW_REQUIRES_INSTALLATION")
        if not 1 <= int(rating) <= 5:
            raise MarketplaceError("MARKETPLACE_REVIEW_INVALID")
        value = {"id": self._id("REV"), "item_id": item_id, "package_id": package["id"], "workspace_id": workspace_id, "user_id": context["user_id"], "rating": int(rating), "comment": redact_text(comment, 1000), "created_at": utc_now()}
        try:
            self.database.add_marketplace_review(value)
        except sqlite3.IntegrityError as exc:
            raise MarketplaceError("MARKETPLACE_REVIEW_EXISTS") from exc
        self._event("REVIEW_CREATED", "SUCCESS", item_id=item_id, metadata={"rating": int(rating), "version": package["version"]})
        return {key: value[key] for key in ("id", "item_id", "rating", "comment", "created_at")}

    def my_items(self, actor: str) -> list[dict[str, Any]]:
        return [self._safe_item(value) for publisher in self.database.list_publishers(actor) for value in self.database.list_marketplace_items(author_id=publisher["id"], published_only=False)]

    def set_item_status(self, actor: str, item_id: str, status: str, *, approval_id: str) -> dict[str, Any]:
        normalized = str(status).upper()
        if normalized not in {"PUBLISHED", "DISABLED", "REMOVED"}:
            raise MarketplaceError("MARKETPLACE_STATUS_INVALID")
        item = self.database.get_marketplace_item(item_id)
        publisher = None if item is None else self.database.get_publisher(str(item["author_id"]))
        if item is None or publisher is None or publisher.get("owner") != actor:
            self._denied("MARKETPLACE_ITEM_NOT_FOUND", item_id=item_id)
        self._consume_approval(actor, approval_id, f"marketplace:item_status:{item_id}:{normalized}")
        self.database.set_marketplace_item_status(item_id, normalized)
        self._event(f"PACKAGE_{normalized}", "SUCCESS", item_id=item_id, publisher_id=str(item["author_id"]))
        return self._safe_item(self.database.get_marketplace_item(item_id) or {})

    def installations(self, actor: str, workspace_id: str) -> list[dict[str, Any]]:
        self._workspace(actor, workspace_id, "tasks:read")
        return self.database.list_marketplace_installations(workspace_id)

    def _workspace(self, actor: str, workspace_id: str, permission: str) -> dict[str, Any]:
        try:
            return self.teams.workspace_context(actor, workspace_id, permission)
        except Exception as exc:
            self._denied("MARKETPLACE_TENANT_DENIED", workspace_id=workspace_id)
            raise MarketplaceError("MARKETPLACE_RESOURCE_NOT_FOUND") from exc

    def _consume_approval(self, actor: str, approval_id: str, action_type: str) -> None:
        if not re.fullmatch(r"APR-[A-Za-z0-9-]{6,64}", approval_id) or not self.database.consume_team_approval(actor, approval_id, action_type):
            self._denied("MARKETPLACE_APPROVAL_REQUIRED", action_type=action_type)

    def _denied(self, code: str, **metadata: Any) -> None:
        self.audit.record(code, severity="SECURITY", source="marketplace", action_result="BLOCKED", **sanitize_metadata(metadata))
        raise MarketplaceError(code)

    def _event(self, event: str, result: str, *, item_id: str | None = None, publisher_id: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        self.database.add_marketplace_event({"id": self._id("MPE"), "item_id": item_id, "publisher_id": publisher_id, "event": event, "result": result[:100], "metadata": sanitize_metadata(metadata or {}), "created_at": utc_now()})

    @staticmethod
    def _safe_publisher(value: dict[str, Any]) -> dict[str, Any]:
        return {key: value.get(key) for key in ("id", "display_name", "status", "created_at", "updated_at")}

    @staticmethod
    def _safe_item(value: dict[str, Any]) -> dict[str, Any]:
        return {key: value.get(key) for key in ("id", "type", "name", "description", "version", "author_id", "author", "category", "risk_level", "status", "downloads", "created_at", "updated_at")}

    @staticmethod
    def _version(value: str) -> tuple[int, int, int, int, str]:
        core, _, prerelease = str(value).partition("-")
        major, minor, patch = (int(part) for part in core.split("."))
        return major, minor, patch, 1 if not prerelease else 0, prerelease
