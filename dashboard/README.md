# Nexora Dashboard

The dashboard is an internal HTTPS application composed of:

- `frontend/` — static same-origin UI;
- `backend/` — TLS HTTP server and request controls;
- `api/` — owner-scoped platform operations;
- `auth/` — scrypt password and server-side sessions;
- `permissions/` — deny-by-default dashboard authorization.

The browser never receives database paths, secrets, system prompts, raw logs,
or OpenClaw credentials. Agent state changes create an approval through the
existing v1.4/v1.5 ApprovalService before an override is applied.
