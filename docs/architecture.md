# Architecture

## Tenant request path (v2.2)

```text
Authenticated request
  -> external identity namespace
  -> organization
  -> active workspace membership
  -> RBAC
  -> Policy / Approval
  -> workspace-scoped repository
```

Organizations and workspaces wrap the existing runtime rather than replacing
it. Existing owner namespaces and JSON state remain compatible; migration 006
adds nullable tenant references to tasks and new collaboration tables.

## Cloud and billing path (v2.3)

```text
Organization -> Subscription -> Plan -> Limits -> Trusted Usage Meter -> Runtime
```

Limit checks happen before supported mutations. Billing endpoints are read-only;
admin changes reuse the existing management task, approval, policy, and audit
path. Cloud Manager records local metadata and has no provider credentials.

Nexora 2.0 preserves the proven runtime packages and adds a public release
boundary. `core/README.md` maps Core to the existing packages without copying
or renaming modules.

```text
Telegram          Browser          External client
   |                  |                  |
allowlist       Dashboard API      /api/v1 + API key
   |                  |                  |
   +------ authentication / owner scope--+
                         |
                   Policy Engine
                         |
              Approval + cancellation
                         |
        TaskService -> Orchestrator -> Workflow
                         |
                  Agent / Skill policy
                         |
             JSON compatibility + SQLite
                         |
               Events / Audit / Metrics
```

## Runtime and workflows

`runtime/` retains TaskManager, Orchestrator, WorkflowEngine, AgentRunner,
providers, transports, validation, and events. `workflows/` contains reviewed
routes. Entrypoints must use package imports; conflicting duplicate packages
are not introduced.

## Agents and policies

The Agent Registry loads eight local manifests. Policy Engine verifies agent
state, tool, workspace path, risk, action type, and approval before execution.
Unknown or disabled agents and undeclared tools fail closed.

## Events, audit, and storage

Task state is written atomically to owner-isolated JSON repositories and
mirrored to SQLite. Migrations are additive and reversible. Events contain
bounded sanitized metadata. Audit records add severity, source, result,
timestamp, and a deterministic hash; raw context and secrets are excluded.

## Dashboard and public API

Frontend calls only the authenticated Dashboard backend. It cannot access
SQLite, shell, Docker, or OpenClaw directly. The public API authenticates
hashed scoped keys, applies rate limits and Policy Engine, and queues tasks. It
does not possess a Gateway token or provider transport.

## Marketplace

Creator submissions enter a declarative-only validation boundary. Verified
publisher ownership, schema and permission validation, compatibility, checksum
integrity, Policy Engine, workspace RBAC, approval, and audit precede
activation. The catalog stores immutable package versions and never loads or
executes publisher code. Installations, reviews, and license metadata are
workspace-scoped.

## Open-source boundary

Core includes runtime, agents, skills, API, dashboard, security, database,
events, tests, and safe examples. Production configuration, VPS automation,
credentials, customer data, private integrations, and commercial skills remain
outside this repository under the boundary documented in `extensions/README.md`.
# Agent Ecosystem v3

Agent Builder, Agent Teams, Planning, Memory, Evaluation, SDK and Agent Security
are additive services above the existing workspace/RBAC, Policy, Approval,
Audit, and SQLite layers. The Dashboard and Public API call the same service
facade; neither bypasses policy or connects directly to OpenClaw.

## Operations layer v3.4

```text
Task Runtime -> Event Bus -> SQLite event journal -> Realtime Service -> SSE -> Dashboard
                                      |
                                      +-> activity / notifications / analytics
```

Migration 011 adds notification, agent-status, and dashboard-metric projections.
The v2.2 `activity_events` journal is reused rather than duplicated. Dashboard
and Public API requests resolve identity, workspace membership, RBAC, and scope
before querying these projections. Realtime is a same-origin authenticated
read stream; it is not a command channel and has no provider or tool access.
