from __future__ import annotations

from typing import Any


class MetricsService:
    def __init__(self, database: Any) -> None:
        self.database = database

    def task_created(self, owner: str, agent: str, skill: str) -> None:
        self.database.record_metric("task_created", 1, owner=owner, labels={"agent": agent})
        self.database.record_metric("skill_call", 1, owner=owner, labels={"skill": skill})

    def api_request(self, owner: str | None, endpoint: str, success: bool) -> None:
        self.database.record_metric("api_request", 1 if success else 0, owner=owner, labels={"endpoint": endpoint})

    def webhook_delivery(self, owner: str, success: bool) -> None:
        self.database.record_metric("webhook_delivery", 1 if success else 0, owner=owner)

    def summary(self, owner: str) -> dict[str, Any]:
        return self.database.metrics_summary(owner)
