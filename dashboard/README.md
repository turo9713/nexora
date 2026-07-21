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

## Dashboard workbench (v3.1)

The Tasks page can create an owner-scoped task, show live progress, continue a
completed or clarifying dialogue, cancel an active task, and download a
sanitized UTF-8 text result. Execution reuses the existing Orchestrator,
AgentRunner, OpenClawProvider, Policy Engine, approval service, and task store.

Dashboard dialogue state is separate from Telegram state and retains at most
12 turns / 12,000 characters for six hours. The Gateway token is read from
`/run/secrets/openclaw_gateway_token`; it is not exposed through environment
variables, API responses, logs, or Docker metadata. The Dashboard container
must join the private OpenClaw network; no Gateway port is published.
