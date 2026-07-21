# Usage metering

Usage events cover task creation/completion/failure, agent and skill runs,
workflow duration, files, documents, and knowledge bytes. Only reviewed internal
sources (`task_runtime`, `workflow_runtime`, `knowledge_service`,
`cloud_manager`, or migration tooling) can append events.

Events are append-only. SQLite triggers reject update and delete operations.
Public API and Dashboard routes expose aggregated monthly values only and offer
no write endpoint. Events contain organization/workspace identifiers, metric,
non-negative integer value, trusted source, and timestamp; they contain no
prompt, message, token, API key, or payment information.

Limits use authoritative current tables for workspace, member, agent, task, and
knowledge storage counts. This prevents forged usage events from increasing or
decreasing entitlement.
