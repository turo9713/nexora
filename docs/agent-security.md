# Agent Security

Each request is evaluated as:

`identity -> organization/workspace membership -> RBAC -> agent/tool/memory scope -> Policy Engine -> approval -> service -> redacted audit`.

Controls are deny-by-default. Unknown tools, unknown memory scopes, cross-tenant resources, executable manifests, shell, root, Docker, secrets, production access, and replayed approvals are rejected. The browser and public API never connect directly to OpenClaw or SQLite.
