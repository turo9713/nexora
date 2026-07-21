# Agent Builder

Nexora 3.0 creates declarative, versioned agent manifests. Builder input contains identity, goal, role, reviewed skills, knowledge references, an allowlist of tools and permissions, memory scope, and approval rules. Creation requires workspace `agents:manage`, an exact one-time approval, Policy Engine authorization, and an audit event.

The builder rejects unknown fields, shell/Docker/root/secret capabilities, executable payloads, invalid semantic versions, and paths outside the workspace. Published version rows and checksums are immutable.

Dashboard: `/agent-center`. API: `GET|POST /api/v1/agent-definitions` with `agent_ecosystem:read` or `agent_ecosystem:manage`.
