from __future__ import annotations

import json
from typing import Any


class PlanError(ValueError):
    pass


class PlanCatalog:
    def __init__(self, database: Any) -> None:
        self.database = database

    @staticmethod
    def _safe(row: dict[str, Any]) -> dict[str, Any]:
        try:
            limits = json.loads(str(row["limits"]))
            features = json.loads(str(row["features"]))
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise PlanError("invalid plan record") from exc
        if not isinstance(limits, dict) or not isinstance(features, dict):
            raise PlanError("invalid plan record")
        return {
            "id": str(row["id"]), "name": str(row["name"]), "tier": int(row["tier"]),
            "limits": limits, "features": features, "status": str(row["status"]),
        }

    def list(self) -> list[dict[str, Any]]:
        return [self._safe(row) for row in self.database.list_plans()]

    def require(self, plan_id: str) -> dict[str, Any]:
        row = self.database.get_plan(str(plan_id).casefold())
        if row is None or row["status"] != "ACTIVE":
            raise PlanError("plan unavailable")
        return self._safe(row)
