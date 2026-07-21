from __future__ import annotations

from typing import Any


EXAMPLES = (
    {"id": "article-outline", "name": "Generate article outline", "input_type": "text", "agent": "content"},
    {"id": "analyze-text", "name": "Analyze text", "input_type": "text", "agent": "analytics"},
    {"id": "review-code-sample", "name": "Review code sample", "input_type": "code", "agent": "developer"},
    {"id": "create-report", "name": "Create report", "input_type": "text", "agent": "research"},
)


class PlaygroundService:
    """A data-only catalogue; execution is intentionally unavailable in v2.1."""

    def __init__(self, audit: Any | None = None) -> None:
        self.audit = audit

    def examples(self) -> dict[str, Any]:
        if self.audit is not None:
            self.audit.record("PLAYGROUND_VIEWED", source="playground", action_result="SANDBOX_ONLY")
        return {
            "mode": "SANDBOX_ONLY",
            "external_writes": False,
            "publishing": False,
            "secrets": False,
            "production_tools": False,
            "items": [dict(item) for item in EXAMPLES],
        }
