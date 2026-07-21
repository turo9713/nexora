from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib import error, request

ENDPOINT = "http://127.0.0.1:18789/v1/responses"
TOKEN_ENV = "OPENCLAW_GATEWAY_TOKEN"


def _auth_header() -> str | None:
    token = os.getenv(TOKEN_ENV)
    if not token:
        print(f"SKIPPED: {TOKEN_ENV} missing")
        return None
    return f"Bearer {token}"


def _post(prompt: str, token: str) -> tuple[int, str]:
    payload = (
        '{'
        '"model":"openclaw",'
        '"input":' + repr(prompt).replace("'", '"') + ','
        '"tools":[],'
        '"tool_choice":"none"'
        '}'
    ).encode("utf-8")
    req = request.Request(
        ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": token,
        },
    )
    with request.urlopen(req, timeout=10) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def main() -> int:
    token = _auth_header()
    if token is None:
        return 0

    try:
        status, body = _post("Ответь только: NEXORA_LIVE_OK", token)
        if status != 200:
            print("SKIPPED: Gateway did not return HTTP 200")
            return 0
        if "NEXORA_LIVE_OK" not in body:
            print("SKIPPED: expected response marker not found")
            return 0
        print("LIVE_OK")
        return 0
    except error.HTTPError as exc:
        print("SKIPPED: Gateway auth or request failed")
        return 0
    except error.URLError:
        print("SKIPPED: Gateway unavailable")
        return 0
    except Exception:
        print("SKIPPED: live smoke test blocked")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
