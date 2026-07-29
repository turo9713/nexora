# Changelog

All notable changes follow Semantic Versioning.

## [4.0.1] - 2026-07-30

### Changed

- Dashboard navigation is grouped into six focused tabs: Work, AI, Team,
  Marketplace, Platform, and Enterprise.
- The active navigation tab now follows the current route, persists for the
  browser session, and remains usable on narrow mobile screens.

## [4.0.0] - 2026-07-28

### Added

- AI Workforce Marketplace with 14 official AI employees, six workflow packs,
  four skills, categories, search, compatibility, ratings, changelogs, pricing
  metadata, documentation, and install/update/uninstall lifecycle.
- One-click declarative provisioning of workspace bindings, memory,
  permissions, workflows, prompts, and settings.
- Protected integration wizard for Telegram, Email, Google, Slack, GitHub,
  Webhook, and API Key secret references.
- My AI Team, Developer Portal, revenue-share accounting foundation, private
  catalog visibility, and Free/Starter/Pro/Team/Business/Enterprise plans.
- Authenticated Dashboard and `/api/v1/workforce` APIs, reversible migration
  013, architecture/ER documentation, and production deployment notes.

### Security

- Package execution remains deny-by-default and passes existing Marketplace,
  Policy Engine, approval, RBAC, tenant isolation, and audit controls.
- Raw integration credentials, shell, Docker, root, production access, and
  direct OpenClaw Gateway access are prohibited.

## [3.5.0] - 2026-07-23

### Added

- Tenant-scoped Enterprise Security Center, policy registry and immutable
  hash-chained security events.
- Approval-gated policy creation, versioning, and rollback without changing
  the existing authentication or runtime execution paths.
- Provider-neutral SAML, OIDC, and OAuth foundation; every external provider
  remains disabled until separately configured.
- SLA calculations, read-only storage integrity/permission checks, deployment
  profiles, and compliance control reporting.
- Authenticated, rate-limited Enterprise Dashboard and `/api/v1` read APIs.
- Reversible migration 012 and enterprise unit, integration, and security tests.

### Security

- Enterprise resources are organization/workspace scoped through the existing
  RBAC and tenant isolation layer.
- The Dashboard remains read-only for policy changes; policy mutations require
  a valid, one-time approval in the service layer.
- Storage checks use read-only SQLite access and do not expose filesystem paths.

## [3.4.2] - 2026-07-22

### Fixed

- All JSON task, history, session, action, approval, context, and audit writers
  now use one atomic private-storage helper with explicit `0600` file and
  `0700` directory modes.
- Telegram tasks are bound to an authorized organization and workspace before
  creation, allowing their durable events to reach the correctly scoped SSE
  Dashboard stream.
- `/tasks` and `/tasks/{id}` consume authenticated workspace-filtered SSE with
  cursor-based reconnect, event-ID deduplication, and a safe manual refresh.
- Telegram `/status` records a sanitized `TELEGRAM_STATUS_VIEWED` audit event
  without invoking the model.

### Security

- Workspace selection is deterministic and membership-checked; user text cannot
  choose a workspace and missing or revoked access fails closed.
- `python -m nexora.storage.repair_permissions` checks or repairs only
  allowlisted state roots without following symbolic links.

## [3.4.0] - 2026-07-22

### Added

- Tenant-scoped `/home`, activity, notifications, workspace overview, agent
  status, operations analytics, and safe onboarding Dashboard pages.
- Authenticated SSE task updates with durable Event Bus cursors, automatic
  reconnect, and workspace filtering instead of browser polling.
- Scoped read-only public API endpoints for dashboard, activity, notifications,
  and agent status.
- Reversible migration 011 for notifications, agent status history, dashboard
  metrics, and indexes over the existing activity journal.

### Security

- Operational projections expose only allowlisted fields; raw metadata,
  context, logs, secrets, and provider/Gateway access remain unavailable.
- All reads retain authentication, RBAC, tenant isolation, rate limits, request
  correlation, and audit. Notification read state requires session CSRF.
- Task Control Center remains read-only and no tool, shell, service, Docker, or
  production mutation was added.

## [3.3.0] - 2026-07-22

### Added

- Read-only Task Control Center with owner-scoped task list, safe task details,
  existing lifecycle progress, and sanitized event timelines.
- Authenticated task list, detail, and event API reads with existing scopes,
  rate limits, request/correlation identifiers, audit, and tenant isolation.

### Security

- Dashboard task mutations were removed from the Task Control Center; the UI
  cannot start, continue, cancel, or otherwise change a task.
- Timeline payloads are allowlisted and exclude raw event metadata, prompts,
  secrets, tracebacks, and Gateway access.
- Workspace-bound tasks require current membership and `tasks:read` RBAC even
  when the caller omits `workspace_id`; shared reads never open another owner's
  JSON context.

## [3.2.0] - 2026-07-22

### Added

- Read-only Agent Control Center with registry metadata, safe task counts, and last activity.
- Authenticated `GET /api/v1/agents/{id}` with existing scopes, rate limits, audit, and workspace isolation.

### Security

- Agent mutation controls were removed from the Dashboard surface; no shell, permission editing, secret access, or Gateway call is available.
- Agent statistics remain owner- and workspace-scoped and expose neither prompts nor manifest source paths.

## [3.1.0] - 2026-07-21

### Added

- Owner-only Dashboard task creation and bounded web dialogue through the existing OpenClaw provider.
- Live task progress polling, safe cancellation, approval handoff, and downloadable sanitized text results.
- Dedicated Dashboard dialogue state with idempotency, 6-hour TTL, 12-turn, and 12,000-character limits.

### Security

- Gateway credentials remain in a read-only secret file and are never returned to the browser or stored in task context.
- Web task writes require an authenticated admin session, CSRF token, deny-by-default permission, Policy check, and audit event.
- Dashboard and Telegram dialogue stores are isolated; Gateway remains private.

## [3.0.0] - 2026-07-21

### Added

- Approval-gated Agent Builder with immutable Manifest v2 versions.
- Workspace-isolated Agent Teams, policy-checked planning, scoped Memory 2.0, and immutable agent evaluations.
- Agent Center, Teams, Memory, Planning, Evaluation, and SDK Dashboard/API foundations.
- Marketplace agent package kinds for single agents, teams, and AI departments.
- Reversible SQLite migration 010 and Python SDK foundation.

### Security

- Agent requests now pass identity, tenant, RBAC, tool, memory-scope, Policy, Approval, and redacted Audit checks.
- No arbitrary code loading, shell, root, Docker, secrets, Gateway exposure, or production mutation was introduced.

## [2.5.0] - 2026-07-21

### Added

- Owner-isolated creator profiles, Creator Dashboard, package analytics, reviews, verification levels, and quality grades.
- Immutable semantic package versions with draft, validation, publication, archive, and approval-protected rollback lifecycles.
- Scoped Creator API reads and reversible SQLite migration 009.

### Security

- Creator administration remains RBAC-, Policy-, Approval-, and Audit-gated; public endpoints expose sanitized profile data only.
- Published checksums and manifests are database-protected and cannot be replaced or deleted.
- No payment data, third-party code execution, production access, or weaker Marketplace validation was introduced.

## [2.4.0] - 2026-07-21

### Added

- Declarative Marketplace catalog for versioned Agents, Skills, Templates, and Integrations.
- Verified publisher workflow, package checksums, checksum-attestation foundation, search, categories, installs, reviews, community licenses, and immutable marketplace events.
- Authenticated Dashboard pages and scoped `/api/v1/marketplace` endpoints.
- Reversible SQLite migration 008 with automatic pre-migration backup and integrity validation.

### Security

- Packages are metadata-only: executable payloads, shell, root, secrets, Docker, privileged, and production access are rejected.
- Installation revalidates the canonical manifest and checksum, passes workspace RBAC and Policy Engine checks, and requires a one-time approval for medium/high-risk packages and all integrations.
- Cross-tenant installation and review access fail closed; no payment provider or automatic external code download is present.

## [2.3.0] - 2026-07-21

### Added

- Four seeded plans, organization subscriptions, trusted-source usage metering, and a fail-closed limits engine.
- Tenant-scoped read-only Billing API and Dashboard views for plans, subscription, usage, and effective limits.
- Approval-only Admin Console operations for plan changes and organization blocking.
- Metadata-only Cloud Manager provisioning with no payment provider or infrastructure allocation.
- Reversible SQLite migration 007 with automatic pre-migration backup, integrity validation, and immutable usage/billing event triggers.

### Security

- External clients cannot write usage, change subscriptions, or access another organization's billing data.
- Quotas are checked before task, workspace, member, or knowledge mutations.
- Plan and account status changes require the protected admin namespace, exact one-time approval, Policy Engine authorization, and audit.
- No real payment processing, Gateway exposure, production deployment, or infrastructure mutation was added.

## [2.2.0] - 2026-07-21

### Added

- Organization and workspace tenancy with hashed external user identities and fail-closed RBAC.
- Workspace-scoped members, agents, skills, tasks, knowledge documents, comments, and activity events.
- Authenticated Dashboard and scoped Public API views for organizations, workspaces, members, and knowledge.
- Reversible SQLite migration 006 plus tenant-isolation, role-escalation, approval-replay, and data-leakage tests.

### Security

- Every workspace resource lookup verifies active organization membership and the required role capability.
- Membership and component changes consume an exact, expiring, one-time approval through the existing Policy Engine.
- Knowledge ingestion rejects secret-like content; tenant audit metadata is redacted and contains no raw external identity.
- Existing single-owner data remains intact and production services require no infrastructure or Gateway change.

## [2.1.0] - 2026-07-21

### Added

- Declarative Workflow Template Registry with five reviewed built-ins and a reversible owner-scoped installation model.
- Authenticated Dashboard and scoped API endpoints for templates and the safe, data-only Playground.
- Community Skills submission structure, onboarding flow, four public demos, and anonymous community metrics.
- Reversible SQLite migration 005 and template security, integration, API, and migration tests.

### Security

- Templates cannot contain executable fields, secrets, Docker/root access, environment values, or production permissions.
- Playground provides examples only; it has no execution, external writes, publication, secrets, or production tools.
- Medium-risk template installation reuses the existing one-time Approval and Policy Engine path.

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
