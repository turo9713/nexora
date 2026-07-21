"""Schema validation helpers for Nexora runtime."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema


class RuntimeValidators:
    def __init__(self, base_path: str):
        self.schemas_dir = Path(base_path) / "schemas"

    def _load_schema(self, name: str) -> dict:
        return json.loads((self.schemas_dir / name).read_text(encoding="utf-8"))

    def _validate(self, schema_name: str, data: dict) -> bool:
        schema = self._load_schema(schema_name)
        jsonschema.validate(instance=data, schema=schema)
        return True

    def validate_task(self, data: dict) -> bool:
        return self._validate("task.schema.json", data)

    def validate_agent_message(self, data: dict) -> bool:
        return self._validate("agent_message.schema.json", data)

    def validate_agent_result(self, data: dict) -> bool:
        return self._validate("agent_result.schema.json", data)

    def validate_approval(self, data: dict) -> bool:
        if data.get("status") == "PENDING":
            raise ValueError("Pending approvals are blocked")
        return self._validate("approval.schema.json", data)
