"""OpenClaw provider adapter for Nexora runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

from .base import AgentProvider, ProviderError
from ..transports.base import Transport, TransportError


class OpenClawProvider(AgentProvider):
    def __init__(self, config: dict | None = None, transport: Transport | None = None) -> None:
        super().__init__(config=config or {})
        self.transport = transport

    def _ensure_transport(self) -> Transport:
        if self.transport is None:
            raise ProviderError("transport_missing: OpenClaw transport is not connected")
        return self.transport

    def _safe_created_at(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _normalize_response(self, response: Dict[str, Any], agent_message: dict) -> dict:
        transport_response = response.get("response") if isinstance(response.get("response"), dict) else response
        return {
            "result_id": str(transport_response.get("result_id") or uuid4()),
            "task_id": str(transport_response.get("task_id") or agent_message.get("task_id") or "unknown-task"),
            "agent": str(transport_response.get("agent") or agent_message.get("to_agent") or "unknown-agent"),
            "status": str(transport_response.get("status") or "SUCCESS"),
            "summary": str(transport_response.get("summary") or "OpenClaw transport response received"),
            "details": transport_response.get("details", {"transport_response": response}),
            "artifacts": list(transport_response.get("artifacts") or []),
            "warnings": list(transport_response.get("warnings") or []),
            "next_action": transport_response.get("next_action"),
            "created_at": str(transport_response.get("created_at") or self._safe_created_at()),
        }

    def execute_agent(self, agent_message: dict) -> dict:
        try:
            transport = self._ensure_transport()
            response = transport.send(agent_message)
            if not isinstance(response, dict):
                raise ProviderError("transport_error: invalid transport response payload")
            return self._normalize_response(response, agent_message)
        except ProviderError:
            raise
        except TransportError as exc:
            raise ProviderError(f"transport_error: {exc}") from exc
        except Exception as exc:  # pragma: no cover
            raise ProviderError(f"transport_error: {exc}") from exc

    def validate_response(self, agent_result: dict) -> bool:
        if not isinstance(agent_result, dict):
            raise ProviderError("Invalid agent result payload")
        return True

    def health_check(self) -> dict:
        transport = self._ensure_transport()
        try:
            return transport.health_check()
        except TransportError as exc:
            raise ProviderError(f"transport_error: {exc}") from exc
