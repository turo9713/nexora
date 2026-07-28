# Nexora Dashboard

The dashboard is an internal HTTPS application composed of:

- `frontend/` — static same-origin UI;
- `backend/` — TLS HTTP server and request controls;
- `api/` — owner-scoped platform operations;
- `auth/` — scrypt password and server-side sessions;
- `permissions/` — deny-by-default dashboard authorization.

The browser never receives database paths, secrets, system prompts, raw logs,
or OpenClaw credentials.

## User Experience and Operations (v3.4)

`/home` is the owner entry point for a workspace-scoped summary. `/activity`,
`/notifications`, `/workspace`, `/agents/status`, `/analytics`, and
`/onboarding` are safe projections of existing tasks, Event Bus records, RBAC,
agent manifests, and billing limits.

Task changes reach the browser through authenticated same-origin Server-Sent
Events at `/api/realtime/tasks`. EventSource reconnects with the last durable
event ID; every read is filtered by an authorized workspace. No frontend timer
polls the task API. The stream and JSON endpoints return only bounded,
allowlisted fields. Every mutation requires the Dashboard session, permission
check, same-origin CSRF token, workspace ownership, and an audit event.

## Agent Workbench

`/workbench` is the user-facing task entry point. It creates a task through the
existing TaskManager, Orchestrator, Policy Engine, Approval Engine, and runtime;
the browser never calls OpenClaw directly. The task view shows workspace-scoped
SSE progress, lifecycle events, the sanitized result, and a safe text download.
Completed tasks can receive a follow-up message, while active tasks can be
cancelled without deleting existing artifacts.

Mutations exist only under `/api/workbench/tasks`. They require an authenticated
admin session, exact Origin and CSRF checks, an authorized workspace, and an
idempotency key. A supplied workspace identifier is never trusted without RBAC
validation. Dangerous requests still stop at `WAITING_APPROVAL`.

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

The `/tasks` surface has no task create, continue, cancel, shell, service
restart, or Gateway operation. Existing TaskManager, Orchestrator, WorkflowEngine,
AgentRunner, Policy Engine, and Approval Engine remain unchanged. Result files
are available only as sanitized read-only downloads, and pending approvals link
to the existing Approval Center.

## Dashboard runtime compatibility (v3.1)

The Dashboard task runtime is exposed only through the authenticated Workbench
facade. The read-only Task Control Center remains isolated from that facade.

Dashboard dialogue state is separate from Telegram state and retains at most
12 turns / 12,000 characters for six hours. The Gateway token is read from
`/run/secrets/openclaw_gateway_token`; it is not exposed through environment
variables, API responses, logs, or Docker metadata. The Dashboard container
must join the private OpenClaw network; no Gateway port is published.
