# Enterprise Operations

Nexora 3.5 adds an Enterprise Policy Layer above the existing identity,
workspace, runtime, and audit components. It does not replace RBAC, the Policy
Engine, approvals, sandboxing, memory encryption, or agent isolation.

Every request resolves an authenticated actor to an active organization and
workspace membership before reading a resource. Unknown, suspended, revoked,
or cross-tenant access fails with the same safe unavailable response.

The Dashboard exposes read-only views at `/security-center`, `/policies`,
`/sla`, `/storage-health`, and `/enterprise`. It never calls OpenClaw directly
and cannot execute tools or shell commands.

Migration 012 is additive and reversible. Before production migration, back up
the SQLite database and verify `PRAGMA integrity_check`. Rollback uses:

```bash
python -c "from pathlib import Path; from nexora.database import SQLiteRepository; SQLiteRepository(Path('runtime/state/database/nexora.sqlite3')).rollback(12)"
```
