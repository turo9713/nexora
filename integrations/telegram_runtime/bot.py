from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urlsplit


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from nexora.integrations.telegram_runtime.handlers import TelegramRuntimeHandlers
from nexora.runtime.agent_runner import AgentRunner
from nexora.runtime.orchestrator import Orchestrator
from nexora.runtime.providers.openclaw_provider import OpenClawProvider
from nexora.runtime.transports.openclaw_transport import OpenClawTransport


TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
OWNER_ENV = "NEXORA_TELEGRAM_OWNER_ID"
GATEWAY_ENDPOINT_ENV = "NEXORA_OPENCLAW_ENDPOINT"
GATEWAY_ENDPOINT_DEFAULT = "http://gateway:18789/v1/responses"
GATEWAY_TOKEN_FILE = Path("/run/secrets/gateway_token")
NAMESPACE_KEY_FILE = Path("/run/secrets/namespace_key")
GATEWAY_MODEL = "openclaw"
GATEWAY_TIMEOUT_SECONDS = 120
HEALTH_FILE = Path("/tmp/nexora-telegram.health")
HEALTH_MAX_AGE_SECONDS = 90


class TelegramAPIError(RuntimeError):
    """A sanitized Telegram Bot API failure."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TelegramBotAPI:
    def __init__(self, token: str) -> None:
        self._base_url = f"https://api.telegram.org/bot{token}"

    def call(self, method: str, payload: dict[str, Any]) -> Any:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        api_request = request.Request(
            f"{self._base_url}/{method}",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with request.urlopen(api_request, timeout=40) as response:
                result = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            raise TelegramAPIError(
                f"Telegram API {method} failed with HTTP {exc.code}",
                status_code=exc.code,
            ) from None
        except error.URLError:
            raise TelegramAPIError(f"Telegram API {method} is unavailable") from None
        except (TimeoutError, json.JSONDecodeError):
            raise TelegramAPIError(f"Telegram API {method} returned an invalid response") from None

        if not result.get("ok"):
            raise TelegramAPIError(f"Telegram API {method} rejected the request")
        return result.get("result")

    def get_updates(self, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "limit": 100,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = self.call("getUpdates", payload)
        return result if isinstance(result, list) else []

    def get_webhook_info(self) -> dict[str, Any]:
        result = self.call("getWebhookInfo", {})
        return result if isinstance(result, dict) else {}

    def get_me(self) -> dict[str, Any]:
        result = self.call("getMe", {})
        return result if isinstance(result, dict) else {}

    def send_message(self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        self.call("sendMessage", payload)

    def answer_callback_query(self, callback_query_id: str, text: str, show_alert: bool = False) -> None:
        self.call(
            "answerCallbackQuery",
            {
                "callback_query_id": callback_query_id,
                "text": text[:180],
                "show_alert": show_alert,
            },
        )


def _load_settings() -> tuple[str, int]:
    token = os.environ.get(TOKEN_ENV, "").strip()
    owner = os.environ.get(OWNER_ENV, "").strip()
    if not token:
        raise RuntimeError(f"{TOKEN_ENV} is not configured")
    if not owner.isdigit():
        raise RuntimeError(f"{OWNER_ENV} must be a numeric Telegram user ID")
    return token, int(owner)


def _load_namespace_key() -> bytes:
    try:
        value = NAMESPACE_KEY_FILE.read_bytes().strip()
    except OSError:
        raise RuntimeError("Nexora namespace key is unavailable") from None
    if len(value) < 32:
        raise RuntimeError("Nexora namespace key is invalid")
    return value


def _gateway_endpoint() -> str:
    endpoint = os.environ.get(GATEWAY_ENDPOINT_ENV, GATEWAY_ENDPOINT_DEFAULT).strip()
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"gateway", "nexora-openclaw-gateway"}
        or parsed.port != 18789
        or parsed.path != "/v1/responses"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(f"{GATEWAY_ENDPOINT_ENV} must reference the internal OpenClaw endpoint")
    return endpoint


def _gateway_authorization() -> str:
    try:
        token = GATEWAY_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        raise RuntimeError("OpenClaw Gateway authentication is unavailable") from None
    if not token:
        raise RuntimeError("OpenClaw Gateway authentication is unavailable")
    return token if token.startswith("Bearer ") else f"Bearer {token}"


def _compose_openclaw_orchestrator() -> Orchestrator:
    base_path = str(WORKSPACE_ROOT / "nexora")
    provider_config = {
        "mode": "openclaw",
        "endpoint": _gateway_endpoint(),
        "auth_reference": "OPENCLAW_GATEWAY_TOKEN",
        "timeout": GATEWAY_TIMEOUT_SECONDS,
    }
    runtime_config = {"agent_provider": provider_config}
    transport = OpenClawTransport(
        endpoint=provider_config["endpoint"],
        auth_reference=_gateway_authorization(),
        timeout=provider_config["timeout"],
    )

    send_openresponses = transport.send

    def send_agent_message(agent_message: dict[str, Any]) -> dict[str, Any]:
        objective = agent_message.get("objective")
        if not isinstance(objective, str) or not objective.strip():
            raise RuntimeError("Agent objective is missing")
        return send_openresponses(
            {
                "model": GATEWAY_MODEL,
                "input": objective,
                "tools": [],
                "tool_choice": "none",
            }
        )

    transport.send = send_agent_message  # type: ignore[method-assign]
    provider = OpenClawProvider(config=provider_config, transport=transport)
    orchestrator = Orchestrator(base_path)
    orchestrator.agents = AgentRunner(
        base_path,
        orchestrator.validators,
        provider=provider,
        config=runtime_config,
    )
    return orchestrator


def _mark_healthy() -> None:
    HEALTH_FILE.touch(mode=0o600, exist_ok=True)


def _healthcheck() -> int:
    try:
        age = time.time() - HEALTH_FILE.stat().st_mtime
    except OSError:
        return 1
    return 0 if 0 <= age <= HEALTH_MAX_AGE_SECONDS else 1


def _safe_command_label(update: dict[str, Any]) -> str:
    if isinstance(update.get("callback_query"), dict):
        return "callback"
    message = update.get("message")
    if not isinstance(message, dict):
        return "non_message"
    text = message.get("text")
    if not isinstance(text, str) or not text.startswith("/"):
        return "text"
    return text.split(maxsplit=1)[0].split("@", 1)[0].lower()[:32]


def _is_owner_private_message(update: dict[str, Any], owner_id: int) -> bool:
    message = update.get("message")
    if not isinstance(message, dict):
        return False
    sender = message.get("from") or {}
    chat = message.get("chat") or {}
    return (
        sender.get("id") == owner_id
        and chat.get("id") == owner_id
        and chat.get("type") == "private"
    )


def main() -> int:
    try:
        token, owner_id = _load_settings()
        namespace_key = _load_namespace_key()
        orchestrator = _compose_openclaw_orchestrator()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    api = TelegramBotAPI(token)

    def notify_owner(text: str, reply_markup: dict[str, Any] | None = None) -> None:
        api.send_message(owner_id, text, reply_markup)

    handlers = TelegramRuntimeHandlers(
        owner_id=owner_id,
        namespace_key=namespace_key,
        orchestrator=orchestrator,
        notifier=notify_owner,
    )
    offset: int | None = None

    try:
        identity = api.get_me()
        if not identity.get("is_bot"):
            print("Telegram API identity is not a bot", file=sys.stderr)
            return 1
        webhook_info = api.get_webhook_info()
        if webhook_info.get("url"):
            print("Telegram webhook is configured; long polling is disabled", file=sys.stderr)
            return 1
        pending = api.get_updates(offset=None, timeout=0)
        if pending:
            offset = max(int(update["update_id"]) for update in pending) + 1
        _mark_healthy()
        print("telegram_api=authenticated webhook=absent polling=started", flush=True)
    except TelegramAPIError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    while True:
        try:
            updates = api.get_updates(offset=offset, timeout=30)
            _mark_healthy()
            for update in updates:
                offset = int(update["update_id"]) + 1
                response = handlers.handle_update(update)
                if response is not None:
                    if response.callback_query_id:
                        api.answer_callback_query(
                            response.callback_query_id,
                            response.callback_answer or "Готово",
                            response.callback_alert,
                        )
                    if response.text and response.chat_id is not None:
                        api.send_message(response.chat_id, response.text, response.reply_markup)
                    print(
                        f"telegram_update=processed command={_safe_command_label(update)}",
                        flush=True,
                    )
                elif not _is_owner_private_message(update, owner_id):
                    print("telegram_update=rejected reason=owner_whitelist", flush=True)
            handlers.reconcile_external_approval()
        except TelegramAPIError as exc:
            print(str(exc), file=sys.stderr)
            if exc.status_code == 409:
                return 1
            time.sleep(3)
        except KeyboardInterrupt:
            handlers.close()
            return 0
        except Exception:
            print("Telegram runtime adapter blocked an internal error", file=sys.stderr)
            time.sleep(3)


if __name__ == "__main__":
    if "--healthcheck" in sys.argv[1:]:
        raise SystemExit(_healthcheck())
    raise SystemExit(main())
