# Multi-tenancy security

Nexora 2.2 treats organization and workspace identifiers as untrusted input.
Possession of an identifier grants no access. The service resolves the
authenticated external namespace to an internal user, verifies active
membership and tenant state, evaluates RBAC, and only then queries a scoped
repository method.

## Controls

- deny-by-default role and scope decisions;
- organization and workspace status enforcement;
- workspace-qualified task, knowledge, comment, component, and activity queries;
- identical unavailable responses for missing and foreign resources;
- exact, expiring, one-time approvals for membership and capability changes;
- Policy Engine remains mandatory after approval;
- audit redaction and no raw Telegram ID, email address, token, or user context;
- secret-like knowledge content is rejected before persistence;
- migration 006 is reversible and retains the v2.1 JSON/history and task owner fields.

## Threat tests

The automated suite exercises cross-workspace and cross-organization reads,
role escalation, approval replay, unauthorized API scopes, unknown roles,
knowledge leakage, migration integrity, and rollback. These tests do not replace
production access review; Dashboard/API deployments must remain authenticated
and OpenClaw Gateway must remain private.
