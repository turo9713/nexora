# Changelog

All notable changes follow Semantic Versioning.

## [2.0.0] - 2026-07-21

### Added

- First GitHub-ready public release boundary for Nexora Core and private
  Extensions.
- MIT license, security policy, code of conduct, public installation guide,
  release checklist, and contributor workflow.
- Hardened four-service Docker deployment, one-command installer, offline demo,
  release archive builder, generic rollback, and GitHub Actions workflows.
- Full-worktree and Git-history secret audit plus release-hardening tests.

### Changed

- Removed VPS-specific rollback and administration scripts from the public
  branch; the `v1.8.0` tag remains the production rollback point.
- Documentation no longer assumes a private `/opt` deployment layout.

### Security

- Public containers are non-root, read-only, capability-free, and receive no
  Docker socket or OpenClaw Gateway token.
- Production configuration, credentials, private integrations, commercial
  skills, customer data, and VPS automation are explicitly excluded.

## [1.8.0] - 2026-07-21

### Added

- Versioned `/api/v1` facade for tasks, agents, skills, and approval-gated
  webhook registration.
- One-time `nx_live_*` API keys with scrypt hashes, expiry, rotation workflow,
  deny-all scopes, and per-key/per-owner/per-endpoint rate limits.
- Signed HTTPS webhooks with bounded timeouts, retries, consecutive-failure
  disable, SSRF checks, and redacted payloads.
- Read-only GitHub integration, approval-only Content publication foundation,
  usage metrics, Dashboard management pages, and hardened `nexora-api` service.
- Reversible SQLite migration 004 and v1.8 rollback tooling.

### Security

- The API service has no Gateway token or provider transport and is bound only
  to VPS localhost pending a trusted public TLS/reverse-proxy deployment.
- API key and webhook lifecycle changes require existing Policy Engine and
  one-time approvals; plaintext secrets are shown only in the approval response.

## [1.7.0] - 2026-07-21

### Added

- Declarative Skill Registry, lifecycle, schema validator, compatibility check,
  metadata-only loader, and skill-scoped policy checks.
- Four reviewed built-in skills: Content Writer, Research, GitHub Assistant,
  and Analytics.
- Reversible SQLite migration 003 for skills, permissions, and lifecycle events.
- Authenticated Dashboard skills UI/API with changes gated by the existing
  Policy Engine, one-time ApprovalService, and audit.
- Skills security, development, testing, and rollback documentation.

### Security

- Skills cannot contain executable entrypoints, shell/root/production access,
  secret references, Docker access, or unreviewed external code.
- Skill manifests are fail-closed, sandbox-required, locally reviewed, and
  restricted to enumerated tools, network modes, and workspace scopes.

## [1.6.0] - 2026-07-21

### Added

- Localhost-only HTTPS control panel with a separate hardened container.
- Scrypt password authentication, signed server-side sessions, expiration,
  brute-force protection, CSRF validation, and security headers.
- Owner-scoped task, agent, approval, audit, and health APIs and UI.
- Agent enable/disable overrides gated by the existing Policy and Approval
  services.
- SQLite migration 002, dashboard tests, documentation, and rollback tooling.

### Security

- Dashboard has no Gateway token, Docker socket, shell API, or public bind.
- Project code is mounted read-only; only runtime state is writable.
- API responses apply redaction and owner-scoped database queries.

## [1.5.1] - 2026-07-21

### Fixed

- Rollback now explicitly restarts the bind-mounted Telegram service and waits
  for its healthcheck, restoring v1.5 automatically if the v1.4 restart fails.

## [1.5.0] - 2026-07-21

### Added

- Git baseline and release metadata.
- Eight-agent registry with fail-closed validation.
- Policy Engine for agent, tool, path, risk, and approval checks.
- Non-destructive SQLite mirror and reversible schema migration.
- Sanitized platform event bus and hashed audit records.
- Owner-only `/health` observability command without LLM usage.
- Platform unit/integration tests, documentation, secret scan, and rollback.

### Security

- Runtime state, user data, logs, credentials, and databases are Git-ignored.
- Event and audit metadata excludes secrets, raw Telegram IDs, and context.
- Existing v1.4 allowlist, idempotency, approval, cancellation, and storage
  controls are preserved.

## [1.4.0] - 2026-07-21

- Production Telegram runtime with task status/history, approvals,
  cancellation, idempotency, safe errors, and owner-isolated state.
