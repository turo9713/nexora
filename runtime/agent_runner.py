"""Agent message/result handling for Nexora runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .providers import MockAgentProvider, OpenClawProvider, ProviderError


class ProviderNotFoundError(ProviderError):
    """Raised when the configured provider mode is not supported."""


class AgentRunner:
    def __init__(self, base_path: str, validators, provider=None, config: dict | None = None):
        self.base_path = base_path
        self.validators = validators
        self.config = config or {"agent_provider": {"mode": "mock"}}
        self.provider = provider or self._select_provider()

    def _select_provider(self):
        mode = self.config.get("agent_provider", {}).get("mode", "mock")
        provider_config = self.config.get("agent_provider", {})
        if mode == "openclaw":
            return OpenClawProvider(self.base_path, provider_config)
        if mode == "mock":
            return MockAgentProvider(self.base_path, provider_config)
        raise ProviderNotFoundError(f"unknown provider mode: {mode}")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def build_message(self, task: dict, to_agent: str) -> dict:
        message = {
            "message_id": str(uuid4()),
            "task_id": task["id"],
            "from_agent": task.get("assigned_agent", "orchestrator"),
            "to_agent": to_agent,
            "objective": task["description"],
            "context": task.get("context", {}),
            "requirements": [],
            "constraints": [],
            "expected_output": "agent_result",
            "created_at": self._now(),
        }
        self.validators.validate_agent_message(message)
        return message

    def execute_message(self, message: dict) -> dict:
        try:
            payload = self.provider.execute_agent(message)
            result = {
                "result_id": str(uuid4()),
                "task_id": message["task_id"],
                "agent": message["to_agent"],
                "status": "SUCCESS",
                "summary": payload["summary"],
                "details": payload["details"],
                "artifacts": payload["artifacts"],
                "warnings": payload["warnings"],
                "next_action": payload["next_action"],
                "created_at": self._now(),
            }
            self.validators.validate_agent_result(result)
            self.provider.validate_response(result)
            return result
        except Exception as exc:
            raise ProviderError(str(exc)) from exc
