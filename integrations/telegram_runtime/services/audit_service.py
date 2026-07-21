from __future__ import annotations

import hashlib
import json
from typing import Any

from nexora.security.audit.redaction import sanitize_metadata

from ..storage.audit_repository import AuditRepository
from .progress_service import utc_now


class AuditService:
    def __init__(self, repository: AuditRepository, database: Any | None = None) -> None:
        self.repository = repository
        self.database = database

    def record(
        self,
        event: str,
        *,
        severity: str | None = None,
        source: str = "telegram_runtime",
        action_result: str | None = None,
        **fields: Any,
    ) -> None:
        timestamp = utc_now()
        severity = severity or self._severity(event)
        metadata = sanitize_metadata({key: value for key, value in fields.items() if value is not None})
        result = str(action_result or fields.get("status") or "RECORDED")[:80]
        canonical = json.dumps(
            {"event": event, "severity": severity, "source": source, "result": result, "timestamp": timestamp, "metadata": metadata},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        record = {
            "at": timestamp,
            "timestamp": timestamp,
            "event": str(event)[:100],
            "severity": severity,
            "source": str(source)[:100],
            "action_result": result,
            "hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "metadata": metadata,
        }
        self.repository.append(record)
        if self.database is not None:
            self.database.insert_audit(record)

    @staticmethod
    def _severity(event: str) -> str:
        upper = event.upper()
        if "DENIED" in upper or "REJECTED" in upper:
            return "SECURITY"
        if "FAILED" in upper or "ERROR" in upper:
            return "ERROR"
        if "WARNING" in upper or "EXPIRED" in upper:
            return "WARNING"
        return "INFO"
