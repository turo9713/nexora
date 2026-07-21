# Nexora Memory

Namespaces:
- user/preferences
- projects/project_context
- tasks/task_history
- decisions/approved_decisions

## user/preferences
Purpose: store owner preferences and stable settings.
Fields: preferred language, style, routing preferences, notification preferences, safe defaults.
Forbidden: passwords, API keys, tokens, private keys, cookies, financial data.

## projects/project_context
Purpose: store project-level context and settings.
Fields: project name, goals, scope, current status, architecture notes, decisions summary.
Forbidden: secrets, credentials, tokens, financial data.

## tasks/task_history
Purpose: store task execution history and outcomes.
Fields: task id, timestamps, status transitions, action history, result summary, artifacts refs, warnings.
Forbidden: secrets, private data, tokens, credentials, financial data.

## decisions/approved_decisions
Purpose: store approved decisions and their rationale.
Fields: decision id, task id, decision text, approved by, approved at, risk level, expiry if relevant.
Forbidden: secrets, credentials, tokens, financial data.
