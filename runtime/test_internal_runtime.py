"""Internal runtime smoke test for Nexora."""

from .orchestrator import Orchestrator


def run_test() -> dict:
    runtime = Orchestrator("/workspace/nexora")
    task_data = {
        "id": "task-demo-001",
        "title": "Создать план разработки Telegram AI-бота",
        "description": "Создать план разработки Telegram AI-бота",
        "created_by": "owner",
        "priority": "NORMAL",
        "assigned_agent": "orchestrator",
        "workflow": "development_flow",
        "context": {"goal": "plan only"},
        "approval_required": False,
    }
    result = runtime.run_task(task_data, "development_flow")
    return {
        "task_status": result["task"]["status"],
        "message_created": "message" in result,
        "result_created": "result" in result,
        "task_id": result["task"]["id"],
    }
