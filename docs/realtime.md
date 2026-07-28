# Realtime Task Updates

Nexora uses authenticated Server-Sent Events (SSE) at
`GET /api/realtime/tasks`. The browser establishes one same-origin EventSource
connection; it does not continuously poll task endpoints.

## Telegram workspace binding (v3.4.2)

Before a Telegram task is created, Nexora resolves and verifies the owner's
active session workspace, sole accessible workspace, or unique personal
workspace. Arbitrary workspace identifiers in message text are ignored. If no
authorized deterministic workspace exists, task creation fails with
`NX_WORKSPACE_REQUIRED`.

Task events carry the internal workspace scope into the durable event journal.
The SSE projection still returns only allowlisted fields to an authenticated
member of that workspace. `/tasks` and `/tasks/{id}` use the event cursor and
`Last-Event-ID`, deduplicate event IDs, and keep a manual refresh fallback.

The durable source is the sanitized SQLite Event Bus journal. The stream sends
only:

- `TASK_CREATED`;
- `TASK_STARTED`;
- `TASK_PROGRESS_UPDATED`;
- `TASK_STAGE_CHANGED`;
- `AGENT_STARTED`;
- `AGENT_FINISHED`;
- `TASK_COMPLETED`;
- `TASK_FAILED`.

Each event contains a bounded event ID, timestamp, task ID, status, stage,
integer progress, agent, and optional safe error code. Raw metadata, prompts,
context, logs, tokens, and provider data are excluded.

EventSource reconnects automatically. `Last-Event-ID` resumes after the last
workspace-authorized durable event. The server closes bounded stream windows
and sends heartbeats so stale connections recover without an unbounded worker.
Authentication, permission checks, rate limits, tenant filtering, and audit run
before stream headers are sent.
