"""Mock agent provider for Nexora runtime."""

from __future__ import annotations

from .base import AgentProvider


class MockAgentProvider(AgentProvider):
    def execute_agent(self, agent_message: dict) -> dict:
        return {
            "summary": f"Mock executed for {agent_message['to_agent']}",
            "details": {"echo": agent_message["objective"]},
            "artifacts": [],
            "warnings": [],
            "next_action": None,
        }

    def validate_response(self, agent_result: dict) -> bool:
        return isinstance(agent_result, dict)

    def health_check(self) -> dict:
        return {"status": "ok", "provider": "mock"}
