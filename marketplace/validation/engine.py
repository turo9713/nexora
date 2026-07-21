from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any


ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
ALLOWED_TYPES = {"AGENT", "SKILL", "TEMPLATE", "INTEGRATION"}
ALLOWED_RISKS = {"LOW", "MEDIUM", "HIGH"}
FORBIDDEN_KEYS = {
    "command", "commands", "entrypoint", "script", "scripts", "code", "hooks",
    "environment", "env", "docker", "container", "secret", "secrets", "credentials",
}
FORBIDDEN_TRUE = {"shell", "root", "secret_access", "docker_access", "production_access", "privileged"}
REQUIRED = {"id", "name", "type", "version", "author", "description", "permissions", "risk_level", "requirements", "compatibility", "security"}
ALLOWED_TOP = REQUIRED | {"category"}


class PackageValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidationResult:
    manifest: dict[str, Any]
    canonical: str
    checksum: str
    signature_status: str


class PackageValidator:
    """Validates declarative metadata only; executable payloads are rejected."""

    def validate(self, value: dict[str, Any], signature: str | None = None) -> ValidationResult:
        if not isinstance(value, dict) or not REQUIRED.issubset(value):
            raise PackageValidationError("MARKETPLACE_MANIFEST_INVALID")
        if not set(value).issubset(ALLOWED_TOP):
            raise PackageValidationError("MARKETPLACE_MANIFEST_FIELD_FORBIDDEN")
        if set(value) & FORBIDDEN_KEYS:
            raise PackageValidationError("MARKETPLACE_EXECUTABLE_PAYLOAD_FORBIDDEN")
        item_id = str(value["id"])
        if not ID.fullmatch(item_id) or not SEMVER.fullmatch(str(value["version"])):
            raise PackageValidationError("MARKETPLACE_ID_OR_VERSION_INVALID")
        if not 2 <= len(str(value["name"]).strip()) <= 120 or not 2 <= len(str(value["author"]).strip()) <= 100 or not 2 <= len(str(value["description"]).strip()) <= 1000:
            raise PackageValidationError("MARKETPLACE_TEXT_INVALID")
        category = str(value.get("category", "other"))
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", category):
            raise PackageValidationError("MARKETPLACE_CATEGORY_INVALID")
        item_type = str(value["type"]).upper()
        risk = str(value["risk_level"]).upper()
        if item_type not in ALLOWED_TYPES or risk not in ALLOWED_RISKS:
            raise PackageValidationError("MARKETPLACE_TYPE_OR_RISK_INVALID")
        security = value.get("security")
        if not isinstance(security, dict) or security.get("sandbox") is not True:
            raise PackageValidationError("MARKETPLACE_SANDBOX_REQUIRED")
        permissions = value.get("permissions")
        if not isinstance(permissions, dict):
            raise PackageValidationError("MARKETPLACE_PERMISSIONS_INVALID")
        if not set(permissions).issubset({"filesystem", "network", "shell"}) or permissions.get("shell") not in {None, False}:
            raise PackageValidationError("MARKETPLACE_PERMISSION_FORBIDDEN")
        filesystem = permissions.get("filesystem", {})
        network = permissions.get("network", {})
        if not isinstance(filesystem, dict) or not isinstance(network, dict):
            raise PackageValidationError("MARKETPLACE_PERMISSIONS_INVALID")
        if not set(filesystem).issubset({"scope"}) or filesystem.get("scope", "workspace") not in {"workspace", "drafts-only", "read-only-data"}:
            raise PackageValidationError("MARKETPLACE_FILESYSTEM_SCOPE_FORBIDDEN")
        if not set(network).issubset({"mode"}) or network.get("mode", "none") not in {"none", "search-only", "github-api-only"}:
            raise PackageValidationError("MARKETPLACE_NETWORK_SCOPE_FORBIDDEN")
        if not set(security).issubset({"sandbox", "secret_access", "docker_access"}) or security.get("secret_access", False) is not False or security.get("docker_access", False) is not False:
            raise PackageValidationError("MARKETPLACE_SECURITY_INVALID")
        self._walk(value)
        requirements = value.get("requirements")
        if not isinstance(requirements, list) or any(not ID.fullmatch(str(item)) for item in requirements):
            raise PackageValidationError("MARKETPLACE_DEPENDENCY_INVALID")
        compatibility = value.get("compatibility")
        if not isinstance(compatibility, dict) or not SEMVER.fullmatch(str(compatibility.get("minimum_nexora", ""))):
            raise PackageValidationError("MARKETPLACE_COMPATIBILITY_INVALID")
        normalized = dict(value)
        normalized.update(type=item_type, risk_level=risk)
        canonical = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        signature_status = "UNSIGNED"
        if signature is not None:
            signature_status = "CHECKSUM_ATTESTED" if signature == f"sha256:{checksum}" else "INVALID"
            if signature_status == "INVALID":
                raise PackageValidationError("MARKETPLACE_SIGNATURE_INVALID")
        return ValidationResult(normalized, canonical, checksum, signature_status)

    def _walk(self, value: Any, depth: int = 0) -> None:
        if depth > 8:
            raise PackageValidationError("MARKETPLACE_MANIFEST_TOO_DEEP")
        if isinstance(value, dict):
            for raw_key, child in value.items():
                key = str(raw_key).casefold()
                if key in FORBIDDEN_KEYS or (key in FORBIDDEN_TRUE and child is True):
                    raise PackageValidationError("MARKETPLACE_PERMISSION_FORBIDDEN")
                self._walk(child, depth + 1)
        elif isinstance(value, list):
            if len(value) > 100:
                raise PackageValidationError("MARKETPLACE_MANIFEST_TOO_LARGE")
            for child in value:
                self._walk(child, depth + 1)
        elif isinstance(value, str) and len(value) > 4000:
            raise PackageValidationError("MARKETPLACE_MANIFEST_TOO_LARGE")
