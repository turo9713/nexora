# Nexora Dashboard

The dashboard is an internal HTTPS application composed of:

- `frontend/` — static same-origin UI;
- `backend/` — TLS HTTP server and request controls;
- `api/` — owner-scoped platform operations;
- `auth/` — scrypt password and server-side sessions;
- `permissions/` — deny-by-default dashboard authorization.

The browser never receives database paths, secrets, system prompts, raw logs,
or OpenClaw credentials.

## Agent Control Center (v3.2)

The Agents page is strictly read-only. It displays safe manifest metadata,
resolved status, owner-scoped completed-task counts, last activity, permissions,
allowed tools, restrictions, and recent tasks. Agent permission changes,
enable/disable actions, shell execution, secrets, and Gateway access are not
available from this Dashboard surface.

## Task Control Center (v3.3)

The Tasks pages are a strictly read-only projection of the existing task
runtime. The list shows the stored status, stage, progress, assigned agent,
workflow, provider mode, and timestamps. Task details expose a sanitized
lifecycle timeline through `GET /api/tasks/{id}/events`; raw event metadata,
conversation context, credentials, and internal runtime payloads are never
returned.

The Dashboard has no task create, continue, cancel, shell, service restart, or
Gateway operation. Existing TaskManager, Orchestrator, WorkflowEngine,
AgentRunner, Policy Engine, and Approval Engine remain unchanged. Result files
are available only as sanitized read-only downloads, and pending approvals link
to the existing read-only Approval Center.

## Dashboard runtime compatibility (v3.1)

The internal Dashboard task runtime implementation remains available for
compatibility and testing, but it is not exposed by the v3.3 Dashboard HTTP or
UI surfaces.

Dashboard dialogue state is separate from Telegram state and retains at most
12 turns / 12,000 characters for six hours. The Gateway token is read from
`/run/secrets/openclaw_gateway_token`; it is not exposed through environment
variables, API responses, logs, or Docker metadata. The Dashboard container
must join the private OpenClaw network; no Gateway port is published.
