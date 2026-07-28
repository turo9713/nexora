#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).absolute().parents[1]
if PROJECT.name != "nexora":
    raise SystemExit("Run this example from a checkout directory named 'nexora'.")
sys.path.insert(0, str(PROJECT.parent))

from nexora.agents.registry import AgentRegistry  # noqa: E402
from nexora.integrations.telegram_runtime.services.approval_service import ApprovalService  # noqa: E402
from nexora.integrations.telegram_runtime.services.task_service import TaskService  # noqa: E402
from nexora.integrations.telegram_runtime.storage.approval_repository import ApprovalRepository  # noqa: E402
from nexora.integrations.telegram_runtime.storage.task_repository import TaskRepository  # noqa: E402
from nexora.security.policies import PolicyEngine  # noqa: E402


PIPELINE = ("research", "content", "qa")


def run_demo(state_root: Path) -> dict[str, object]:
    namespace = hashlib.sha256(b"nexora-public-demo").hexdigest()
    session = "demo-offline-session"
    tasks = TaskService(TaskRepository(state_root / "tasks"))
    approvals = ApprovalService(ApprovalRepository(state_root / "approvals"))
    agents = AgentRegistry(PROJECT / "agents").load()
    policy = PolicyEngine(agents, PROJECT)

    task = tasks.create(namespace, "Создай статью про искусственный интеллект", session)
    task = tasks.transition(namespace, task["task_id"], "PLANNING", stage="Safe offline plan", progress=20)
    for progress, agent_id in zip((45, 70, 85), PIPELINE, strict=True):
        decision = policy.evaluate(agent_id, path=PROJECT / "examples", risk="LOW")
        if not decision.allowed:
            raise RuntimeError("demo policy denied reviewed pipeline")
        task = tasks.transition(
            namespace, task["task_id"], "IN_PROGRESS",
            stage=f"{agent_id}: offline draft metadata", progress=progress,
        )

    task = tasks.transition(namespace, task["task_id"], "WAITING_APPROVAL", stage="Demo approval", progress=90)
    approval = approvals.create(
        namespace, task["task_id"], session, "demo_result",
        "Return the local demo result", "No publication or external side effect",
    )
    result, _ = approvals.decide(namespace, approval["approval_id"], session, "approve")
    if result != "APPROVED":
        raise RuntimeError("demo approval failed")
    tasks.update_fields(
        namespace, task["task_id"],
        result_summary="Offline draft passed Research, Content, QA and one-time approval; nothing was published.",
    )
    task = tasks.transition(namespace, task["task_id"], "COMPLETED", stage="Safe local result", progress=100)
    return {
        "status": "PASS",
        "task_id": task["task_id"],
        "workflow": list(PIPELINE) + ["approval", "result"],
        "final_status": task["status"],
        "network": "disabled",
        "published": False,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="nexora-demo-") as temporary:
        print(json.dumps(run_demo(Path(temporary)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
