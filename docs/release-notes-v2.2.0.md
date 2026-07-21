# Nexora v2.2.0

Nexora 2.2 adds the platform layer for organizations and secure team
collaboration without changing the existing runtime or production deployment.

Highlights:

- fail-closed RBAC roles and active-membership checks;
- isolated organizations and workspaces;
- workspace-scoped tasks, agents, skills, knowledge, comments, and activity;
- Dashboard and scoped API team views;
- reversible SQLite migration 006;
- approval replay, role escalation, tenant IDOR, leakage, and rollback tests.

Upgrade by taking a database backup, deploying the code, and running normal
startup migration validation. Rollback migration 006 restores schema version 5
without deleting the retained v2.1 file storage. The OpenClaw Gateway does not
need to restart.
