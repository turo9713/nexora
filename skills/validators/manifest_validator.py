from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import yaml


class SkillValidationError(RuntimeError):
    code = "SKILL_VALIDATION_FAILED"


class SkillManifestValidator:
    """Validate declarative manifests; executable plugin payloads are unsupported."""

    FORBIDDEN_KEYS = {
        "command", "exec", "script", "entrypoint", "docker", "root", "sudo",
        "secret", "secrets", "token", "password", "environment", "env",
        "telegram_token", "api_key",
    }
    FORBIDDEN_TEXT = re.compile(
        r"(?i)(?:/etc/|/root/|/run/secrets|\.env(?:\b|/)|docker\.sock|telegram[_-]?token|api[_-]?key)"
    )

    def __init__(self, schema_path: Path, *, platform_version: str = "1.7.0") -> None:
        self.schema_path = Path(schema_path)
        self.platform_version = platform_version

    def validate_file(self, path: Path) -> dict[str, Any]:
        path = Path(path)
        if path.is_symlink() or not path.is_file() or path.suffix not in {".yaml", ".yml"}:
            raise SkillValidationError("SKILL_VALIDATION_FAILED: manifest unavailable")
        schema = self._schema()
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise SkillValidationError("SKILL_VALIDATION_FAILED: manifest unreadable") from exc
        if not isinstance(raw, dict):
            raise SkillValidationError("SKILL_VALIDATION_FAILED: manifest must be an object")
        try:
            jsonschema.Draft202012Validator(schema).validate(raw)
        except jsonschema.ValidationError as exc:
            location = ".".join(str(item) for item in exc.absolute_path) or "manifest"
            raise SkillValidationError(f"SKILL_VALIDATION_FAILED: invalid {location}") from exc
        self._deny_forbidden(raw)
        minimum = str(raw.get("compatibility", {}).get("min_platform") or "1.7.0")
        if self._version(minimum) > self._version(self.platform_version):
            raise SkillValidationError("SKILL_VALIDATION_FAILED: incompatible platform version")
        return raw

    def _schema(self) -> dict[str, Any]:
        if self.schema_path.is_symlink() or not self.schema_path.is_file():
            raise SkillValidationError("SKILL_VALIDATION_FAILED: schema unavailable")
        try:
            schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator.check_schema(schema)
        except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
            raise SkillValidationError("SKILL_VALIDATION_FAILED: schema invalid") from exc
        return schema

    def _deny_forbidden(self, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = str(key).casefold().replace("-", "_")
                if normalized in self.FORBIDDEN_KEYS:
                    raise SkillValidationError("SKILL_VALIDATION_FAILED: forbidden permission")
                self._deny_forbidden(item)
        elif isinstance(value, list):
            for item in value:
                self._deny_forbidden(item)
        elif isinstance(value, str) and self.FORBIDDEN_TEXT.search(value):
            raise SkillValidationError("SKILL_VALIDATION_FAILED: forbidden scope")

    @staticmethod
    def _version(value: str) -> tuple[int, int, int]:
        try:
            parts = tuple(int(item) for item in value.split("."))
        except ValueError as exc:
            raise SkillValidationError("SKILL_VALIDATION_FAILED: invalid version") from exc
        if len(parts) != 3:
            raise SkillValidationError("SKILL_VALIDATION_FAILED: invalid version")
        return parts
