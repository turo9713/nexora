from __future__ import annotations

from typing import Any, Dict

from .base import Transport


class MockTransport(Transport):
    """Transport for internal tests only."""

    def __init__(self, controlled_response: Dict[str, Any] | None = None) -> None:
        self.controlled_response = controlled_response or {
            "request_id": "mock-request-1",
            "task_id": "mock-task-1",
            "agent": "mock-agent",
            "status": "SUCCESS",
            "summary": "raw transport response",
            "details": {"transport": "mock", "kind": "raw"},
            "artifacts": [],
            "warnings": [],
            "next_action": None,
        }

    def send(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "request": request,
            "response": self.controlled_response,
        }

    def health_check(self) -> Dict[str, Any]:
        return {
            "status": "ok",
            "connected": True,
            "transport": "mock",
        }
