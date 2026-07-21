"""Nexora internal orchestrator entrypoint.

This module wires together task management, workflow routing, agent
execution, approval gating, and schema validation inside the workspace-only
runtime.
"""

from .task_manager import TaskManager
from .workflow_engine import WorkflowEngine
from .agent_runner import AgentRunner
from .approval_manager import ApprovalManager
from .validators import RuntimeValidators


class Orchestrator:
    def __init__(self, base_path: str = "/workspace/nexora"):
        self.validators = RuntimeValidators(base_path)
        self.tasks = TaskManager(self.validators)
        self.workflows = WorkflowEngine(base_path, self.validators)
        self.agents = AgentRunner(base_path, self.validators)
        self.approvals = ApprovalManager(self.validators)

    def run_task(self, task_data: dict, workflow_name: str) -> dict:
        task = self.tasks.create_task(task_data)
        next_agent = self.workflows.next_agent(workflow_name, task["status"])
        if self.approvals.is_required(task):
            approval = self.approvals.create_pending(task, next_agent)
            task = self.tasks.update_status(task["id"], "WAITING_APPROVAL", approval_id=approval["approval_id"])
            return {"task": task, "approval": approval, "next_agent": next_agent}

        message = self.agents.build_message(task, next_agent)
        result = self.agents.execute_message(message)
        task = self.tasks.complete_task(task["id"], result)
        return {"task": task, "message": message, "result": result}
