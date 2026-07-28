# Deploying Nexora 4.0

1. Stop before production mutation and create the normal database, state, and
   Git bundle backups.
2. Run the test suite and secret scan against the exact release commit.
3. Apply database migration 013 using the existing repository migration
   command. Verify SQLite integrity and schema version 13.
4. Start only updated API and Dashboard services. The Dashboard bootstraps the
   signed-in tenant's official declarative catalog idempotently.
5. Verify authenticated catalog reads, an installation in a test workspace,
   created resource bindings, audit events, and tenant isolation.
6. Do not restart OpenClaw Gateway; v4 does not change it.

Rollback removes only v4 installation metadata and the Starter/Business plan
seeds through `013_ai_workforce.down.sql`. It does not delete legacy
Marketplace packages, tasks, workspace content, or secret material. Always
retain the pre-deploy backup even after a successful integrity check.
