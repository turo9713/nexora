# Usage metrics

Metrics are owner-scoped counters and durations stored in migration 004. The
Dashboard presents tasks today, success percentage, average completion time,
active agents, agent usage/errors, and skill calls/errors.

Labels are allowlisted and bounded. Tokens, prompts, Telegram IDs, Authorization
headers, webhook secrets, full task context, and user messages are not metrics.
Metrics are operational counters, not billing records.
