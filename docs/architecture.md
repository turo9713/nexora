# Architecture

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

## Open-source boundary

Core includes runtime, agents, skills, API, dashboard, security, database,
events, tests, and safe examples. Production configuration, VPS automation,
credentials, customer data, private integrations, and commercial skills remain
outside this repository under the boundary documented in `extensions/README.md`.
