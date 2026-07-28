from __future__ import annotations

import json
import re
import secrets
from typing import Any

from nexora.integrations.telegram_runtime.services.progress_service import utc_now
from nexora.marketplace import MarketplaceError, MarketplaceService
from nexora.security.audit.redaction import redact_text, sanitize_metadata

from .catalog import CATEGORIES, official_catalog


class AIWorkforceError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AIWorkforceService:
    """SaaS-facing orchestration layer over the existing declarative Marketplace."""

    INTEGRATIONS = {"TELEGRAM", "EMAIL", "GOOGLE", "SLACK", "GITHUB", "WEBHOOK", "API_KEY"}

    def __init__(self, marketplace: MarketplaceService) -> None:
        self.marketplace = marketplace
        self.database = marketplace.database
        self.teams = marketplace.teams
        self.audit = marketplace.audit

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}-{secrets.token_hex(8).upper()}"

    def bootstrap_official(self, actor: str) -> dict[str, int]:
        publishers = self.database.list_publishers(actor)
        publisher = next((value for value in publishers if value.get("display_name") == "Nexora Official"), None)
        if publisher is None:
            publisher = self.database.create_publisher({
                "id": self._id("PUB"), "owner": actor, "display_name": "Nexora Official",
                "status": "VERIFIED", "created_at": utc_now(), "updated_at": utc_now(),
            })
        elif publisher.get("status") != "VERIFIED":
            self.database.set_publisher_status(str(publisher["id"]), "VERIFIED")
        created = 0
        updated = 0
        for definition in official_catalog():
            manifest = definition["manifest"]
            existing = self.database.get_marketplace_item(manifest["id"])
            if existing is None:
                self.marketplace.publish(actor, str(publisher["id"]), manifest)
                created += 1
            self.database.upsert_marketplace_metadata({
                "item_id": manifest["id"], **definition["metadata"],
                "created_at": existing.get("created_at") if existing else utc_now(), "updated_at": utc_now(),
            })
            updated += 1
        self.audit.record("WORKFORCE_CATALOG_BOOTSTRAPPED", source="workforce", action_result="SUCCESS", created=created, indexed=updated)
        return {"created": created, "indexed": updated}

    def catalog(self, actor: str, *, workspace_id: str | None = None, search: str | None = None, category: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
        if category and category.casefold() not in CATEGORIES:
            raise AIWorkforceError("MARKETPLACE_CATEGORY_INVALID")
        if workspace_id:
            self._workspace(actor, workspace_id, "tasks:read")
        values = self.marketplace.catalog(search=search, category=category, item_type=self._type_for_kind(kind))
        result = []
        for value in values:
            metadata = self.database.get_marketplace_metadata(str(value["id"]))
            if metadata is None:
                continue
            if kind and metadata["listing_kind"] != kind.upper():
                continue
            if metadata["visibility"] != "PUBLIC" and not self._metadata_visible(actor, metadata):
                continue
            item = self._safe_listing(value, metadata)
            if workspace_id:
                installation = self.database.get_workforce_installation(workspace_id, str(value["id"]))
                item["installation_status"] = installation.get("status") if installation else "NOT_INSTALLED"
                item["installed_version"] = installation.get("version") if installation else None
            result.append(item)
        return result

    def item(self, actor: str, item_id: str, *, workspace_id: str | None = None) -> dict[str, Any]:
        value = self.marketplace.item(item_id, include_manifest=True)
        metadata = self.database.get_marketplace_metadata(item_id)
        if metadata is None or (metadata["visibility"] != "PUBLIC" and not self._metadata_visible(actor, metadata)):
            raise AIWorkforceError("MARKETPLACE_ITEM_NOT_FOUND")
        result = self._safe_listing(value, metadata)
        result["manifest"] = value["manifest"]
        result["versions"] = value["versions"]
        result["reviews"] = value["reviews"]
        result["rating"] = round(sum(int(review["rating"]) for review in value["reviews"]) / len(value["reviews"]), 2) if value["reviews"] else 0
        if workspace_id:
            self._workspace(actor, workspace_id, "tasks:read")
            result["installation"] = self.database.get_workforce_installation(workspace_id, item_id)
        return result

    def install(self, actor: str, workspace_id: str, item_id: str, *, version: str | None = None, approval_id: str | None = None, auto_update: bool = False) -> dict[str, Any]:
        context = self._workspace(actor, workspace_id, "skills:manage")
        base = self.marketplace.install(actor, workspace_id, item_id, version=version, approval_id=approval_id)
        package = self.database.get_marketplace_package(item_id, str(base["version"]))
        metadata = self.database.get_marketplace_metadata(item_id)
        if package is None or metadata is None:
            raise AIWorkforceError("WORKFORCE_PACKAGE_INCOMPLETE")
        manifest = json.loads(package["manifest"])
        definition = next((value for value in official_catalog() if value["manifest"]["id"] == item_id), None)
        workforce = {} if definition is None else definition.get("workforce", {})
        now = utc_now()
        current = self.database.get_workforce_installation(workspace_id, item_id)
        installation = self.database.upsert_workforce_installation({
            "id": current["id"] if current else self._id("WFI"),
            "marketplace_installation_id": base["id"], "workspace_id": workspace_id, "item_id": item_id,
            "version": base["version"], "employee_key": f"{workspace_id}:{item_id}", "status": "ACTIVE",
            "auto_update": bool(auto_update and metadata.get("auto_update")),
            "configuration": {"organization_id": context["organization_id"], "listing_kind": metadata["listing_kind"]},
            "created_at": current.get("created_at") if current else now, "updated_at": now,
        })
        self.database.replace_workforce_resources(str(installation["id"]), self._resources(installation, manifest, workforce))
        self.audit.record("AI_EMPLOYEE_INSTALLED" if metadata["listing_kind"] == "EMPLOYEE" else "MARKETPLACE_ASSET_INSTALLED", source="workforce", action_result="SUCCESS", workspace_id=workspace_id, item_id=item_id, version=base["version"])
        return self._safe_installation(installation)

    def update(self, actor: str, workspace_id: str, item_id: str, *, version: str, approval_id: str | None = None) -> dict[str, Any]:
        current = self.database.get_workforce_installation(workspace_id, item_id)
        if current is None or current.get("status") != "ACTIVE":
            raise AIWorkforceError("WORKFORCE_INSTALLATION_NOT_FOUND")
        if str(current["version"]) == version:
            return self._safe_installation(current)
        return self.install(actor, workspace_id, item_id, version=version, approval_id=approval_id, auto_update=bool(current.get("auto_update")))

    def uninstall(self, actor: str, workspace_id: str, item_id: str, *, approval_id: str) -> dict[str, Any]:
        self._workspace(actor, workspace_id, "skills:manage")
        current = self.database.get_workforce_installation(workspace_id, item_id)
        if current is None:
            raise AIWorkforceError("WORKFORCE_INSTALLATION_NOT_FOUND")
        self.marketplace._consume_approval(actor, approval_id, f"workforce:uninstall:{workspace_id}:{item_id}")
        self.database.rollback_marketplace_installation(workspace_id, item_id, str(current["version"]))
        self.database.set_workforce_status(workspace_id, item_id, "UNINSTALLED")
        self.audit.record("AI_EMPLOYEE_UNINSTALLED", source="workforce", action_result="SUCCESS", workspace_id=workspace_id, item_id=item_id)
        return {"item_id": item_id, "workspace_id": workspace_id, "status": "UNINSTALLED"}

    def request_integration(self, actor: str, workspace_id: str, item_id: str, provider: str, *, secret_reference: str | None, configuration: dict[str, Any]) -> dict[str, Any]:
        self._workspace(actor, workspace_id, "skills:manage")
        normalized = provider.upper()
        if normalized not in self.INTEGRATIONS:
            raise AIWorkforceError("INTEGRATION_PROVIDER_INVALID")
        if secret_reference and not re.fullmatch(r"[A-Z][A-Z0-9_]{2,100}", secret_reference):
            raise AIWorkforceError("SECRET_REFERENCE_INVALID")
        if any(key.casefold() in {"token", "secret", "password", "api_key", "authorization"} for key in configuration):
            raise AIWorkforceError("INLINE_SECRET_FORBIDDEN")
        installation = self.database.get_workforce_installation(workspace_id, item_id)
        if installation is None or installation.get("status") != "ACTIVE":
            raise AIWorkforceError("WORKFORCE_INSTALLATION_NOT_FOUND")
        now = utc_now()
        result = self.database.upsert_integration_wizard({
            "id": self._id("INT"), "installation_id": installation["id"], "workspace_id": workspace_id,
            "provider": normalized, "secret_reference": secret_reference,
            "configuration": sanitize_metadata(configuration), "status": "PENDING", "created_at": now, "updated_at": now,
        })
        self.audit.record("WORKFORCE_INTEGRATION_REQUESTED", source="workforce", action_result="WAITING_APPROVAL", workspace_id=workspace_id, item_id=item_id, provider=normalized)
        return result

    def activate_integration(self, actor: str, workspace_id: str, item_id: str, provider: str, *, approval_id: str) -> dict[str, Any]:
        self._workspace(actor, workspace_id, "skills:manage")
        normalized = provider.upper()
        installation = self.database.get_workforce_installation(workspace_id, item_id)
        if installation is None:
            raise AIWorkforceError("WORKFORCE_INSTALLATION_NOT_FOUND")
        pending = self.database.get_integration_wizard(str(installation["id"]), normalized)
        if pending is None or pending.get("status") != "PENDING":
            raise AIWorkforceError("INTEGRATION_REQUEST_NOT_FOUND")
        self.marketplace._consume_approval(actor, approval_id, f"workforce:integration:{workspace_id}:{item_id}:{normalized}")
        result = self.database.upsert_integration_wizard({
            **pending, "status": "ACTIVE", "updated_at": utc_now(),
        })
        self.audit.record("WORKFORCE_INTEGRATION_CONNECTED", source="workforce", action_result="SUCCESS", workspace_id=workspace_id, item_id=item_id, provider=normalized)
        return result

    def team(self, actor: str, workspace_id: str) -> list[dict[str, Any]]:
        self._workspace(actor, workspace_id, "tasks:read")
        result = []
        for value in self.database.list_workforce_installations(workspace_id):
            tasks = int(value.get("tasks") or 0)
            completed = int(value.get("completed_tasks") or 0)
            result.append({
                "id": value["item_id"], "name": redact_text(value["name"], 120), "status": value["status"],
                "version": value["version"], "last_activity": value.get("last_activity"),
                "tasks": tasks, "success_rate": round(completed * 100 / tasks, 1) if tasks else 0,
                "load": "IDLE" if not value.get("last_activity") else "ACTIVE",
                "cost_cents": (self.database.get_marketplace_metadata(value["item_id"]) or {}).get("price_cents", 0),
                "memory": "WORKSPACE_BOUND", "errors": max(0, tasks - completed),
            })
        return result

    def developer_portal(self, actor: str) -> dict[str, Any]:
        publishers = self.database.list_publishers(actor)
        return {
            "publishers": publishers,
            "packages": self.marketplace.my_items(actor),
            "earnings": [self.database.marketplace_creator_earnings(value["id"]) | {"publisher_id": value["id"]} for value in publishers],
            "payments_enabled": False,
            "commission_bps": 1500,
        }

    def _resources(self, installation: dict[str, Any], manifest: dict[str, Any], workforce: dict[str, Any]) -> list[dict[str, Any]]:
        now = utc_now()
        values = [
            ("WORKSPACE_BINDING", "primary", {"workspace_id": installation["workspace_id"]}),
            ("PERMISSIONS", "manifest", manifest.get("permissions", {})),
            ("SETTINGS", "default", workforce.get("settings", {"external_actions": False})),
        ]
        for resource_type, key in (("MEMORY_PROFILE", "memory_profile"), ("PROMPT", "system_prompt"), ("WORKFLOW", "workflow_pack")):
            if key in workforce:
                values.append((resource_type, "default", {"value": workforce[key]}))
        return [{"id": self._id("WFR"), "resource_type": kind, "resource_key": key, "configuration": config, "created_at": now} for kind, key, config in values]

    def _workspace(self, actor: str, workspace_id: str, permission: str) -> dict[str, Any]:
        try:
            return self.teams.workspace_context(actor, workspace_id, permission)
        except Exception as exc:
            raise AIWorkforceError("WORKFORCE_RESOURCE_NOT_FOUND") from exc

    def _metadata_visible(self, actor: str, metadata: dict[str, Any]) -> bool:
        organization_id = metadata.get("organization_id")
        if metadata.get("visibility") == "ORGANIZATION" and organization_id:
            return any(value["id"] == organization_id for value in self.teams.list_organizations(actor))
        return False

    @staticmethod
    def _type_for_kind(kind: str | None) -> str | None:
        return {"EMPLOYEE": "AGENT", "WORKFLOW": "TEMPLATE", "SKILL": "SKILL", "INTEGRATION": "INTEGRATION"}.get(str(kind or "").upper())

    @staticmethod
    def _safe_listing(value: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        return {
            **{key: value.get(key) for key in ("id", "type", "name", "description", "version", "author", "category", "risk_level", "status", "downloads", "created_at", "updated_at")},
            **{key: metadata.get(key) for key in ("listing_kind", "tags", "price_cents", "currency", "changelog", "compatibility", "screenshots", "documentation", "auto_update", "visibility")},
        }

    @staticmethod
    def _safe_installation(value: dict[str, Any]) -> dict[str, Any]:
        return {key: value.get(key) for key in ("id", "workspace_id", "item_id", "version", "employee_key", "status", "auto_update", "created_at", "updated_at")}
