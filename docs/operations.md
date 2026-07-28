# Operations and Diagnostics

## Data model

Migration 011 creates `notifications`, `agent_status_history`, and
`dashboard_metrics`. It adds indexes to the existing `activity_events` and
`task_events` journals. It does not replace task JSON/history, change workflow
definitions, or delete v1.4-compatible data.

Before migration 011, SQLite creates a mode-600 `.pre-v11.backup` and verifies
integrity. Rollback removes only v3.4 tables and indexes:

```bash
python -c "from pathlib import Path; from nexora.database import SQLiteRepository; SQLiteRepository(Path('runtime/state/database/nexora.sqlite3')).rollback(11)"
```

Stop the Dashboard/API processes before a manual rollback. Production rollback
requires a separate operational approval. OpenClaw Gateway is not involved.

## Diagnostics

```bash
python -m pytest tests/test_operations_v34.py tests/test_operations_api_v34.py dashboard/tests/test_operations_v34.py -q
python -m pytest -q
```

Check `/healthz` for process health, then use authenticated `/api/dashboard`
and `/api/realtime/tasks`. A healthy SSE response has content type
`text/event-stream`; HTTP 401/403 is not a successful stream.

Operations analytics calculate task and agent outcomes from terminal states,
derive workflow success from sanitized workflow fields in task events, and use
stage event frequency only as a coarse bottleneck signal.

## Security invariants

- deny by default and existing RBAC;
- workspace filtering before database projection;
- no raw metadata, context, logs, or secrets;
- no direct Dashboard-to-Gateway call;
- no tools, shell, Docker socket, or production mutation;
- audit for reads, denials, stream access, and notification state changes.
