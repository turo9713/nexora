from __future__ import annotations

import json
from typing import Any, Dict
from urllib import error, request as urllib_request

from .base import Transport, TransportError


class OpenClawTransport(Transport):
    def __init__(self, endpoint: str | None = None, auth_reference: str | None = None, timeout: float | None = None) -> None:
        self.endpoint = endpoint or "http://127.0.0.1:18789/v1/responses"
        self.auth_reference = auth_reference
        self.timeout = timeout

    def _auth_header(self) -> str:
        if not self.auth_reference:
            raise TransportError("authentication_error: missing auth_reference")
        return self.auth_reference

    def _request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(
            self.endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": self._auth_header(),
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    raise TransportError("invalid_response: empty response")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise TransportError(f"invalid_response: {exc}") from exc
        except error.HTTPError as exc:
            if exc.code in (401, 403):
                raise TransportError(f"authentication_error: {exc.code}") from exc
            raise TransportError(f"connection_error: {exc.code}") from exc
        except error.URLError as exc:
            reason = str(getattr(exc, "reason", exc))
            if "timed out" in reason.lower():
                raise TransportError(f"timeout: {reason}") from exc
            raise TransportError(f"connection_error: {reason}") from exc
        except TimeoutError as exc:
            raise TransportError(f"timeout: {exc}") from exc

    def send(self, request: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "model": request.get("model"),
            "input": request.get("input") or request.get("messages") or request,
            "tools": request.get("tools", []),
            "tool_choice": request.get("tool_choice", "none"),
        }
        return self._request(payload)

    def health_check(self) -> Dict[str, Any]:
        response = self.send({"model": "health-check", "input": "ping", "tools": [], "tool_choice": "none"})
        return {
            "status": "ok",
            "connected": True,
            "transport": "openclaw",
            "endpoint": self.endpoint,
            "response": response,
        }
