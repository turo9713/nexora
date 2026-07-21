"""Provider layer tests for Nexora runtime."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import jsonschema

from .agent_runner import AgentRunner, ProviderNotFoundError
from .providers import MockAgentProvider, OpenClawProvider
from .validators import RuntimeValidators


@pytest.fixture()
def validators() -> MagicMock:
    validator = MagicMock(spec=RuntimeValidators)
    validator.validate_agent_message.return_value = True
    validator.validate_agent_result.return_value = True
    return validator


@pytest.fixture()
def mock_agent_message() -> dict:
    return {
        "message_id": "msg-1",
        "task_id": "task-1",
        "from_agent": "orchestrator",
        "to_agent": "worker-1",
        "objective": "do the thing",
        "context": {},
        "requirements": [],
        "constraints": [],
        "expected_output": "agent_result",
        "created_at": "2026-07-20T14:38:00+00:00",
    }


@pytest.fixture()
def agent_result_schema() -> dict:
    schema_path = Path("/workspace/nexora/schemas/agent_result.schema.json")
    return json.loads(schema_path.read_text(encoding="utf-8"))


class TestProviderLayer:
    def test_mock_provider_flow(self, validators: MagicMock, mock_agent_message: dict) -> None:
        runner = AgentRunner(
            base_path="/workspace/nexora",
            validators=validators,
            config={"agent_provider": {"mode": "mock"}},
        )

        assert isinstance(runner.provider, MockAgentProvider)

        execute_spy = MagicMock(wraps=runner.provider.execute_agent)
        validate_spy = MagicMock(wraps=runner.provider.validate_response)
        runner.provider.execute_agent = execute_spy
        runner.provider.validate_response = validate_spy

        result = runner.execute_message(mock_agent_message)

        assert execute_spy.called
        assert validate_spy.called
        assert validators.validate_agent_result.called
        assert result["status"] == "SUCCESS"
        assert result["task_id"] == mock_agent_message["task_id"]
        assert result["agent"] == mock_agent_message["to_agent"]
        assert set(["result_id", "task_id", "agent", "status", "summary", "details", "artifacts", "warnings", "next_action", "created_at"]).issubset(result.keys())
        assert result["summary"] == "Mock executed for worker-1"
        assert result["details"] == {"echo": "do the thing"}

    def test_mock_provider_result_schema(self, mock_agent_message: dict, agent_result_schema: dict) -> None:
        runner = AgentRunner(
            base_path="/workspace/nexora",
            validators=MagicMock(spec=RuntimeValidators),
            config={"agent_provider": {"mode": "mock"}},
        )

        runner.validators.validate_agent_message.return_value = True
        runner.validators.validate_agent_result.return_value = True

        result = runner.execute_message(mock_agent_message)

        required_fields = [
            "result_id",
            "task_id",
            "agent",
            "status",
            "summary",
            "details",
            "artifacts",
            "warnings",
            "next_action",
            "created_at",
        ]
        for field in required_fields:
            assert field in result

        assert isinstance(result["result_id"], str)
        assert isinstance(result["task_id"], str)
        assert isinstance(result["agent"], str)
        assert isinstance(result["status"], str)
        assert isinstance(result["summary"], str)
        assert isinstance(result["details"], dict)
        assert isinstance(result["artifacts"], list)
        assert isinstance(result["warnings"], list)
        assert result["next_action"] is None or isinstance(result["next_action"], str)
        assert isinstance(result["created_at"], str)
        assert result["status"] in {"SUCCESS", "WARNING", "FAILED", "NEEDS_APPROVAL"}

        jsonschema.validate(instance=result, schema=agent_result_schema)

    def test_unknown_provider_raises(self, validators: MagicMock) -> None:
        with pytest.raises(ProviderNotFoundError, match="unknown provider mode"):
            AgentRunner(
                base_path="/workspace/nexora",
                validators=validators,
                config={"agent_provider": {"mode": "unknown"}},
            )

    def test_provider_health(self) -> None:
        mock_provider = MockAgentProvider(base_path="/workspace/nexora", config={"mode": "mock"})
        openclaw_provider = OpenClawProvider(base_path="/workspace/nexora", config={"mode": "openclaw"})

        mock_health = mock_provider.health_check()
        openclaw_health = openclaw_provider.health_check()

        assert mock_health == {"status": "ok", "provider": "mock"}
        assert openclaw_health["status"] == "ok"
        assert openclaw_health["provider"] == "openclaw"
        assert openclaw_health["connected"] is False
