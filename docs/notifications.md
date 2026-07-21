# Notifications

Notifications are local operational records for:

- `TASK_COMPLETED`;
- `TASK_FAILED`;
- `APPROVAL_REQUIRED`;
- `AGENT_ERROR`;
- `SECURITY_ALERT`.

Rows store an internal user key and workspace ID, never a Telegram ID or token.
Messages are bounded and redacted before the API projects them. Reads require
the current workspace membership. A notification can be marked read only by
its owner through an authenticated, authorized, same-origin CSRF-protected
Dashboard request. Repeating the operation is idempotent.

Public API v1 is read-only and does not expose the mark-read operation.
