from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import yaml


class TemplateValidationError(RuntimeError):
    code = "TEMPLATE_VALIDATION_FAILED"


class TemplateValidator:
    """Validate data-only templates and reject executable or privileged content."""

    FORBIDDEN_KEYS = {
        "command", "exec", "script", "entrypoint", "docker", "root", "sudo",
        "secret", "secrets", "token", "password", "environment", "env", "webhook",
    }
    FORBIDDEN_TEXT = re.compile(
        r"(?i)(?:/etc/|/root/|/run/secrets|\.env(?:\b|/)|docker\.sock|ssh[_-]?key|api[_-]?key)"
    )

    def __init__(self, schema_path: Path, *, platform_version: str = "2.1.0") -> None:
        self.schema_path = Path(schema_path)
        self.platform_version = platform_version

    def validate_file(self, path: Path) -> dict[str, Any]:
        path = Path(path)
        if path.is_symlink() or not path.is_file() or path.name != "template.yaml":
            raise TemplateValidationError("TEMPLATE_VALIDATION_FAILED: manifest unavailable")
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.Draft202012Validator(schema).validate(raw)
        except (OSError, UnicodeError, yaml.YAMLError, json.JSONDecodeError, jsonschema.SchemaError, jsonschema.ValidationError) as exc:
            raise TemplateValidationError("TEMPLATE_VALIDATION_FAILED: invalid manifest") from exc
        if not isinstance(raw, dict):
            raise TemplateValidationError("TEMPLATE_VALIDATION_FAILED: manifest must be an object")
        self._deny_forbidden(raw)
        minimum = str(raw.get("compatibility", {}).get("min_platform") or "2.1.0")
        if self._version(minimum) > self._version(self.platform_version):
            raise TemplateValidationError("TEMPLATE_VALIDATION_FAILED: incompatible platform")
        if str(raw["permissions"]["level"]).upper() not in {"LOW", "MEDIUM"}:
            raise TemplateValidationError("TEMPLATE_VALIDATION_FAILED: permission escalation")
        return raw

    def _deny_forbidden(self, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).casefold().replace("-", "_") in self.FORBIDDEN_KEYS:
                    raise TemplateValidationError("TEMPLATE_VALIDATION_FAILED: forbidden field")
                self._deny_forbidden(item)
        elif isinstance(value, list):
            for item in value:
                self._deny_forbidden(item)
        elif isinstance(value, str) and self.FORBIDDEN_TEXT.search(value):
            raise TemplateValidationError("TEMPLATE_VALIDATION_FAILED: forbidden value")

    @staticmethod
    def _version(value: str) -> tuple[int, int, int]:
        try:
            parts = tuple(int(part) for part in value.split("."))
        except ValueError as exc:
            raise TemplateValidationError("TEMPLATE_VALIDATION_FAILED: invalid version") from exc
        if len(parts) != 3:
            raise TemplateValidationError("TEMPLATE_VALIDATION_FAILED: invalid version")
        return parts
