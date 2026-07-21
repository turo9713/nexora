from __future__ import annotations

from typing import Any, Dict
from urllib import error
from unittest.mock import MagicMock, patch

import pytest

from .transports.openclaw_transport import OpenClawTransport, TransportError


class _FakeResponse:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    def read(self) -> bytes:
        import json

        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_health_check_uses_config_and_returns_status() -> None:
    transport = OpenClawTransport(endpoint="http://127.0.0.1:18789/v1/responses", auth_reference="secret://ref", timeout=1.5)

    with patch("nexora.runtime.transports.openclaw_transport.urllib_request.urlopen", return_value=_FakeResponse({"ok": True, "response": "NEXORA_OK"})) as mocked:
        result = transport.health_check()

    assert mocked.called
    assert result["connected"] is True
    assert result["transport"] == "openclaw"
    assert "endpoint" in result


def test_send_success_returns_raw_gateway_response() -> None:
    transport = OpenClawTransport(endpoint="http://127.0.0.1:18789/v1/responses", auth_reference="secret://ref", timeout=1.5)
    raw_response = {"response": "NEXORA_OK", "id": "gw-1", "status": "completed"}

    with patch("nexora.runtime.transports.openclaw_transport.urllib_request.urlopen", return_value=_FakeResponse(raw_response)):
        result = transport.send({"model": "demo", "tools": [], "tool_choice": "none", "input": "ping"})

    assert result == raw_response


def test_authentication_error_raises_controlled_error() -> None:
    transport = OpenClawTransport(endpoint="http://127.0.0.1:18789/v1/responses", auth_reference="secret://bad", timeout=1.5)

    with patch("nexora.runtime.transports.openclaw_transport.urllib_request.urlopen", side_effect=error.HTTPError(url=transport.endpoint, code=401, msg="Unauthorized", hdrs=None, fp=None)):
        with pytest.raises(TransportError) as exc:
            transport.send({"model": "demo", "input": "ping"})

    assert "authentication_error" in str(exc.value)


def test_timeout_raises_controlled_error() -> None:
    transport = OpenClawTransport(endpoint="http://127.0.0.1:18789/v1/responses", auth_reference="secret://ref", timeout=0.1)

    with patch("nexora.runtime.transports.openclaw_transport.urllib_request.urlopen", side_effect=TimeoutError("timed out")):
        with pytest.raises(TransportError) as exc:
            transport.send({"model": "demo", "input": "ping"})

    assert "timeout" in str(exc.value)
