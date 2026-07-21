from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from uuid import uuid4


BASE_PATH = Path(__file__).resolve().parents[1]
WORKSPACE_PATH = BASE_PATH.parent
if str(WORKSPACE_PATH) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_PATH))

from nexora.runtime.agent_runner import AgentRunner
from nexora.runtime.orchestrator import Orchestrator
from nexora.runtime.providers.openclaw_provider import OpenClawProvider
from nexora.runtime.task_manager import TaskManager
from nexora.runtime.transports.openclaw_transport import OpenClawTransport
from nexora.runtime.workflow_engine import WorkflowEngine


WORKFLOW_NAME = "development_flow"
TASK_DESCRIPTION = "Создай краткий план разработки Telegram AI-бота"
PROVIDER_CONFIG = {
    "agent_provider": {
        "mode": "openclaw",
        "endpoint": "http://127.0.0.1:18789/v1/responses",
        "auth_reference": "OPENCLAW_GATEWAY_TOKEN",
        "timeout": 120,
    }
}
AGENT_CHAIN = [
    "TaskManager",
    "Orchestrator",
    "WorkflowEngine",
    "AgentRunner",
    "OpenClawProvider",
]


def _gateway_token() -> str:
    token = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "").strip()
    if not token:
        raise RuntimeError("OPENCLAW_GATEWAY_TOKEN is not available")
    return token


def _compose_runtime() -> tuple[Orchestrator, WorkflowEngine]:
    orchestrator = Orchestrator(str(BASE_PATH))
    validators = orchestrator.validators
    task_manager = TaskManager(validators)
    workflow_engine = WorkflowEngine(str(BASE_PATH), validators)

    token = _gateway_token()
    authorization = token if token.startswith("Bearer ") else f"Bearer {token}"
    provider_config = PROVIDER_CONFIG["agent_provider"]
    transport = OpenClawTransport(
        endpoint=provider_config["endpoint"],
        auth_reference=authorization,
        timeout=provider_config["timeout"],
    )

    send_openresponses = transport.send

    def send_agent_message(agent_message: dict) -> dict:
        return send_openresponses(
            {
                "model": "openclaw",
                "input": agent_message["objective"],
                "tools": [],
                "tool_choice": "none",
            }
        )

    transport.send = send_agent_message  # type: ignore[method-assign]
    provider = OpenClawProvider(config=provider_config, transport=transport)
    agent_runner = AgentRunner(
        str(BASE_PATH),
        validators,
        provider=provider,
        config=PROVIDER_CONFIG,
    )

    orchestrator.tasks = task_manager
    orchestrator.workflows = workflow_engine
    orchestrator.agents = agent_runner
    return orchestrator, workflow_engine


def main() -> int:
    orchestrator, workflow_engine = _compose_runtime()
    workflow = workflow_engine.load_workflow(WORKFLOW_NAME)
    if workflow["status"] != "LOADED":
        raise RuntimeError(f"workflow is not available: {WORKFLOW_NAME}")

    task_id = f"nexora-real-demo-{uuid4()}"
    outcome = orchestrator.run_task(
        {
            "id": task_id,
            "title": "Nexora real agent workflow demo",
            "description": TASK_DESCRIPTION,
            "created_by": "nexora-runtime-smoke",
            "workflow": WORKFLOW_NAME,
            "context": {"smoke_test": True},
            "approval_required": False,
        },
        WORKFLOW_NAME,
    )

    task = outcome["task"]
    agent_result = outcome["result"]
    if task["status"] != "COMPLETED":
        raise RuntimeError(f"unexpected final task status: {task['status']}")

    print(
        json.dumps(
            {
                "task_id": task["id"],
                "provider_mode": PROVIDER_CONFIG["agent_provider"]["mode"],
                "workflow_route": workflow["route"],
                "agent_chain": AGENT_CHAIN,
                "agent_result": agent_result,
                "final_task_status": task["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
