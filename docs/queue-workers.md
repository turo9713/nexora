# Queue & Workers

Nexora 4.8 keeps `TaskManager`, `Orchestrator`, `WorkflowEngine`,
`AgentRunner`, providers and transports unchanged. The existing Telegram and
Dashboard adapters submit workflow turns to migration 014's durable
`execution_jobs` queue.

## Lifecycle

```text
Task → QUEUED → transactional claim → RUNNING
                                  ├─ SUCCEEDED
                                  ├─ FAILED
                                  ├─ CANCELLED
                                  └─ RETRY_WAIT → transactional claim
```

Each adapter owns a bounded worker group. Claims use a SQLite immediate
transaction, priority order and a unique `(worker_group, idempotency_key)`
constraint. A job therefore cannot be claimed twice from an available state.
The task-level idempotency record remains the second protection against a
duplicate workflow turn.

Default priority is 5 on the bounded 0–9 scale. Default attempts are 2. Only
`NX_TIMEOUT` and `NX_PROVIDER_ERROR` are retryable, with bounded exponential
delay. Authentication, permission, validation, cancellation and internal
errors fail closed.

## Recovery and cancellation

Running jobs have an expiring lease. On process start, an expired job is
returned to the queue only if its attempt budget remains. Otherwise the job
and task fail with the safe `NX_TIMEOUT` code. Cancellation marks queued and
delayed retry jobs `CANCELLED`; a running worker checks the task cancellation
flag before each significant stage and discards late results.

## Dashboard

`GET /api/queue` and `/queue` are authenticated, authorized, rate-limited,
audited, owner-scoped and workspace-scoped. The projection includes only:

- job and task identifiers;
- safe title, worker group, priority and state;
- queue position, attempts, task progress and timestamps;
- a safe error code.

It excludes session IDs, idempotency keys, worker lease identity, prompt
content, context, secrets and raw exceptions. The UI is read-only.

## Operations

Check migration and queue state:

```bash
python - <<'PY'
from pathlib import Path
from nexora.database import SQLiteRepository
db = SQLiteRepository(Path("/path/to/nexora.sqlite3"))
print(db.schema_version())
print(db.check())
PY
```

Before deployment, back up state, SQLite and Git, verify checksums, run the
full test suite and secret scan, then restart only the Dashboard/API/Telegram
components that load the changed Python code. OpenClaw Gateway does not need a
restart.

Rollback is fail-closed: stop affected queue consumers, preserve a fresh
backup, run `scripts/rollback-nexora-v4.8.sh` against the database, restore
the reviewed v4.7 code, then restart only affected services. Never run the
down migration while queue consumers are active.
