# Realtime Task Updates

Nexora uses authenticated Server-Sent Events (SSE) at
`GET /api/realtime/tasks`. The browser establishes one same-origin EventSource
connection; it does not continuously poll task endpoints.

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
