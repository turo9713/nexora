"""Workflow routing for Nexora runtime."""

from __future__ import annotations

from pathlib import Path

import yaml


class WorkflowEngine:
    def __init__(self, base_path: str, validators):
        self.base_path = Path(base_path)
        self.validators = validators
        self.workflows_dir = self.base_path / "workflows"

    def load_workflow(self, workflow_name: str) -> dict:
        path = self.workflows_dir / f"{workflow_name}.yaml"
        if not path.exists():
            return {"name": workflow_name, "route": [], "status": "MISSING"}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        route = data.get("route", [])
        if isinstance(route, dict):
            route = route.get(workflow_name, [])
        return {"name": workflow_name, "route": route, "status": "LOADED", "raw": data}

    def next_agent(self, workflow_name: str, current_status: str) -> str:
        workflow = self.load_workflow(workflow_name)
        route = workflow.get("route", [])
        if not route:
            return "orchestrator"
        if current_status in {"CREATED", "PLANNING"}:
            return route[0]
        if current_status == "RUNNING" and len(route) > 1:
            return route[1]
        return route[-1]
