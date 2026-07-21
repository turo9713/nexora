# Nexora Skills

Nexora 2.0 skills are declarative capability profiles. They do not contain or
load executable code. The flow is:

`Task -> Agent -> Skill Selector -> Skill Policy Check -> metadata activation -> Audit`

## Registry and lifecycle

The registry loads only reviewed manifests from `skills/manifests/` and records
`DISCOVERED`, `VALIDATED`, `INSTALLED`, then `ACTIVE` or `DISABLED`. Runtime
states are stored in SQLite migration 003; lifecycle events are append-only.
`FAILED` and `REMOVED` require an administrator review before reuse.

Built-ins:

- `content-writer`: Content agent, drafts read/write, no network.
- `research`: Research agent, workspace read-only, search-only network.
- `github-assistant`: Developer agent, workspace read-only, disabled initially.
- `analytics`: Analytics agent, read-only data scope, disabled initially.

Dashboard actions never mutate state immediately. They create a task and a
one-time approval bound to the dashboard session and existing ApprovalService.
The approved action is rechecked by Policy Engine before execution.

## Diagnostics

```bash
cd /workspace
/workspace/nexora/runtime/.venv/bin/python -m pytest -q nexora/tests/test_skills.py nexora/dashboard/tests
curl -k https://127.0.0.1:18880/healthz
```

The authenticated API exposes safe manifest fields and sanitized lifecycle
events at `/api/skills` and `/api/skills/{id}`.

## Manifest development

Every manifest declares an ID, semantic version, description, owning agent,
bounded filesystem/network permissions, risk, allowed tools, sandbox state,
approval policy, compatibility, and default status. The JSON Schema rejects
unknown properties, shell access, production access, and unsupported tools.

New manifests require source review, validation tests, policy tests, and an
explicit registry entry. External code download or execution is not supported.
