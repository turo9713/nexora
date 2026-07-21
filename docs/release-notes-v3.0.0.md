# Nexora v3.0.0

Nexora v3.0.0 introduces the AI Agent Ecosystem foundation while preserving the v2.5 security model.

## Highlights

- Approval-gated Agent Builder with declarative Manifest v2 and immutable semantic versions.
- Workspace-isolated Agent Teams with explicit leader/member roles and ordered workflows.
- Policy-checked planning that produces bounded proposals without executing them.
- Encrypted-at-rest PERSONAL, WORKSPACE, and AGENT memory scopes.
- Immutable, server-originated evaluation metrics for accuracy, reliability, safety, speed, and cost.
- Marketplace package kinds for single agents, agent teams, and AI departments.
- Authenticated Dashboard/API surfaces and an in-process Python SDK foundation.
- Reversible SQLite migration 010 with automatic backup and integrity checks.

## Security boundary

No arbitrary code loader, shell bridge, Docker access, root access, secret access, direct Gateway client, public Gateway binding, production deployment, or infrastructure restart is included. Agent/team activation consumes an exact one-time approval and all access remains workspace/RBAC/Policy/Audit gated.

## Upgrade

Run the normal migration path after a verified backup. The migration creates additive v3 tables and retains all v2.5 data. `scripts/rollback-nexora-v3.0.sh` rolls back only migration 010 after creating an integrity-checked database backup; it does not touch OpenClaw, Docker, or VPS services.
