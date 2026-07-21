# Nexora Runtime Layer

Minimal internal runtime layer for workspace-only orchestration.

## Stack
- Python 3
- JSON Schema validation
- Workspace-local file-based runtime state

## Responsibilities
- Task lifecycle management
- Workflow routing
- Agent message/result handling
- Approval gating
- Schema validation

## Modules
- `orchestrator.py` - entrypoint for internal orchestration
- `task_manager.py` - create and update tasks
- `workflow_engine.py` - resolve next agent from workflow definitions
- `agent_runner.py` - build agent messages and validate results
- `approval_manager.py` - create and check approvals
- `validators.py` - schema validation helpers

## Scope
- No Telegram integration
- No external APIs
- No security rule changes
- No host actions
