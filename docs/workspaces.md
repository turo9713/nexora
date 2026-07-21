# Workspaces

A workspace is the security boundary for tasks, agents, skills, knowledge,
comments, and activity. Access always resolves this chain:

```text
Request -> User -> Organization -> Workspace -> RBAC -> Policy -> Resource
```

Every repository query includes the workspace identifier and every service call
verifies active membership first. A caller who guesses an identifier from a
different workspace or organization receives the same unavailable response as
for a missing resource.

## Team tasks

Existing task rows remain compatible. Nexora 2.2 optionally attaches
`organization_id`, `workspace_id`, `creator_id`, and `assignee_id`. The original
owner namespace remains in place for safe rollback to 2.1. Team comments and
activity reference the same workspace and cannot be listed across tenants.

## Agents and skills

Workspace assignments are allowlists, not permission grants. Assigning an agent
or skill requires ADMIN or OWNER, Policy Engine approval, and a one-time approval
record. The agent/skill manifest remains the upper bound on its capabilities.

Use `GET /api/v1/workspaces`; create with `POST /api/v1/workspaces`. Dashboard
views are available at `/workspaces`.
