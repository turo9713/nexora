from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest
from jsonschema import validate

from .providers.openclaw_provider import OpenClawProvider, ProviderError
from .transports.mock_transport import MockTransport


class TrackingMockTransport(MockTransport):
    def __init__(self, controlled_response: Dict[str, Any] | None = None) -> None:
        super().__init__(controlled_response=controlled_response)
        self.send_calls: list[Dict[str, Any]] = []
        self.health_calls = 0

    def send(self, request: Dict[str, Any]) -> Dict[str, Any]:
        self.send_calls.append(request)
        return super().send(request)

    def health_check(self) -> Dict[str, Any]:
        self.health_calls += 1
        return super().health_check()


@pytest.fixture()
def agent_result_schema() -> Dict[str, Any]:
    schema_path = Path(__file__).with_name("agent_result.schema.json")
    return __import__("json").loads(schema_path.read_text(encoding="utf-8"))


def test_openclaw_provider_with_mock_transport(agent_result_schema: Dict[str, Any]) -> None:
    transport = TrackingMockTransport(
        controlled_response={
            "summary": "mock transport response",
            "artifacts": [],
            "warnings": [],
            "next_action": None,
        }
    )
    provider = OpenClawProvider(transport=transport)

    result = provider.execute_agent({"to_agent": "demo-agent"})

    assert transport.send_calls == [{"to_agent": "demo-agent"}]
    assert result["summary"] == "mock transport response"
    assert result["details"]["agent"] == "demo-agent"
    validate(instance=result, schema=agent_result_schema)


def test_health_check_calls_transport_health_check() -> None:
    transport = TrackingMockTransport()
    provider = OpenClawProvider(transport=transport)

    result = provider.health_check()

    assert transport.health_calls == 1
    assert result["transport"] == "mock"


@pytest.mark.parametrize("method_name", ["execute_agent", "health_check"])
def test_missing_transport_raises_provider_error(method_name: str) -> None:
    provider = OpenClawProvider()

    with pytest.raises(ProviderError):
        if method_name == "execute_agent":
            provider.execute_agent({"to_agent": "demo-agent"})
        else:
            provider.health_check()


def test_schema_compatibility(agent_result_schema: Dict[str, Any]) -> None:
    transport = TrackingMockTransport(
        controlled_response={
            "summary": "schema compatible",
            "artifacts": [],
            "warnings": [],
            "next_action": None,
        }
    )
    provider = OpenClawProvider(transport=transport)
    result = provider.execute_agent({"to_agent": "demo-agent"})

    validate(instance=result, schema=agent_result_schema)
