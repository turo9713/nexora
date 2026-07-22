# Enterprise Policies

Supported types are `AGENT_POLICY`, `DATA_POLICY`, `ACCESS_POLICY`,
`WORKFLOW_POLICY`, and `SECURITY_POLICY`. Policies belong to one organization;
versions are immutable records with a changelog and approval reference.

Create, update, and rollback require an OWNER-level `security:manage` decision,
a valid one-time approval bound to the exact action, and a successful existing
Policy Engine decision. Rules that enable shell, external writes, root, secret
access, Docker access, sandbox bypass, or approval bypass are rejected.

The Dashboard policy page is deliberately read-only.
