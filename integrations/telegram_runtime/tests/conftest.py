from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

import nexora.integrations.telegram_runtime.handlers as handlers_module
from nexora.integrations.telegram_runtime.handlers import TelegramRuntimeHandlers


OWNER_ID = 100
NAMESPACE_KEY = b"nexora-test-namespace-key-32-bytes-minimum"


class FakeWorkflows:
    def load_workflow(self, name: str) -> dict[str, Any]:
        return {"status": "LOADED", "route": ["orchestrator", "developer", "qa", "owner"]}


class FakeOrchestrator:
    def __init__(
        self,
        responses: list[str] | None = None,
        block: bool = False,
        error: Exception | None = None,
    ) -> None:
        self.responses = responses or ["Готово"]
        self.block = block
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.started = threading.Event()
        self.release = threading.Event()
        if not block:
            self.release.set()
        self.workflows = FakeWorkflows()

    def run_task(self, task: dict[str, Any], workflow_name: str) -> dict[str, Any]:
        self.calls.append(task)
        self.started.set()
        self.release.wait(timeout=5)
        if self.error is not None:
            raise self.error
        text = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        return {
            "task": {**task, "status": "COMPLETED"},
            "result": {
                "result_id": f"result-{len(self.calls)}",
                "agent": "developer",
                "status": "SUCCESS",
                "summary": "fallback",
                "details": {
                    "transport_response": {
                        "output": [{"content": [{"type": "output_text", "text": text}]}]
                    }
                },
            },
        }


def owner_message(update_id: int, text: str, owner_id: int = OWNER_ID) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "from": {"id": owner_id},
            "chat": {"id": owner_id, "type": "private"},
            "text": text,
        },
    }


def callback_update(
    update_id: int,
    data: str,
    *,
    owner_id: int = OWNER_ID,
    callback_id: str = "callback-1",
) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": callback_id,
            "from": {"id": owner_id},
            "message": {"chat": {"id": owner_id, "type": "private"}},
            "data": data,
        },
    }


def wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not reached before timeout")


@pytest.fixture(autouse=True)
def disable_rate_limit(monkeypatch):
    monkeypatch.setattr(handlers_module, "MIN_MESSAGE_INTERVAL_SECONDS", 0)


@pytest.fixture
def handler_factory(tmp_path: Path):
    handlers: list[TelegramRuntimeHandlers] = []

    def factory(
        orchestrator: FakeOrchestrator | None = None,
        notifier=None,
        suffix: str = "default",
        artifact_notifier=None,
    ):
        handler = TelegramRuntimeHandlers(
            owner_id=OWNER_ID,
            namespace_key=NAMESPACE_KEY,
            orchestrator=orchestrator or FakeOrchestrator(),
            notifier=notifier,
            artifact_notifier=artifact_notifier,
            state_path=tmp_path / suffix / "state",
            context_path=tmp_path / suffix / "context",
        )
        handlers.append(handler)
        return handler

    yield factory

    for handler in handlers:
        handler.close()
