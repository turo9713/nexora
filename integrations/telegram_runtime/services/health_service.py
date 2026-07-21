from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any


class HealthService:
    """Local, no-LLM health aggregation for the authorized Telegram owner."""

    def __init__(
        self,
        database: Any,
        registry: Any,
        storage_root: Path,
        telegram_health_file: Path = Path("/tmp/nexora-telegram.health"),
    ) -> None:
        self.database = database
        self.registry = registry
        self.storage_root = Path(storage_root)
        self.telegram_health_file = telegram_health_file

    def snapshot(self, namespace: str) -> dict[str, Any]:
        summary = self.database.health_summary(namespace)
        registry_health = self.registry.health()
        return {
            "runtime": "OK",
            "telegram": "OK" if self._telegram_ok() else "WARNING",
            "storage": "OK" if self._storage_ok() else "ERROR",
            "database": "OK" if self.database.check() else "ERROR",
            "agents_loaded": int(registry_health["enabled"]),
            "active_tasks": summary.active_tasks,
            "completed_today": summary.completed_today,
            "failed_access": summary.failed_access,
            "pending_approvals": summary.pending_approvals,
        }

    def _telegram_ok(self) -> bool:
        try:
            age = time.time() - self.telegram_health_file.stat().st_mtime
            return 0 <= age <= 90
        except OSError:
            return False

    def _storage_ok(self) -> bool:
        try:
            return self.storage_root.is_dir() and not self.storage_root.is_symlink() and os.access(self.storage_root, os.R_OK | os.W_OK)
        except OSError:
            return False
