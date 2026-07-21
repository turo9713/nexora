# Public API security

- deny-all scopes and scrypt-hashed, expiring API keys;
- one-time secret display and approval-gated create/disable/delete/rotation;
- per-key, per-owner, and per-endpoint rate limiting;
- TLS-only service, bounded bodies, request/correlation IDs, safe errors;
- owner filters and equal not-found responses protect against IDOR;
- API audits are redacted and never include headers or plaintext credentials;
- API container is non-root, read-only, capability-free, without Docker socket,
  Gateway/Telegram secrets, host network, or direct provider transport;
- API host port is loopback-only; public exposure requires a separate security
  review, trusted certificate, reverse proxy, and firewall validation.

External task creation only validates and queues through TaskService after Agent
Policy and active Skill checks. It does not synchronously execute an LLM,
production action, shell command, or OpenClaw request.
