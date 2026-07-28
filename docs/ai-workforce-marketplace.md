# AI Workforce Marketplace

Nexora 4.0 adds an additive SaaS layer over the existing Marketplace, Policy
Engine, approvals, billing, workspaces, memory, audit, and analytics services.
It does not create a second runtime and never calls OpenClaw Gateway directly.

## Catalog

The official catalog contains 14 AI employees, six workflow packs, and four
skills. Categories are Business, Marketing, Development, Analytics, Support,
HR, Finance, Automation, and Content. Every card exposes its author, semantic
version, compatibility, rating, install count, changelog, price metadata, tags,
skills, requested permissions, screenshots, and documentation.

An AI employee is a validated Marketplace `AGENT`, a workflow pack is a
`TEMPLATE`, and a skill is a `SKILL`. This mapping preserves all v2.x and v3.x
Marketplace APIs and installation records.

## One-click installation

Installation always resolves an authenticated owner, organization, and
workspace, then passes the existing Marketplace validator and policy checks.
The installer creates declarative, workspace-scoped resources:

- workspace binding;
- memory profile;
- permission profile;
- default workflows;
- default system prompt;
- default settings.

It does not execute package code, shell commands, Docker operations, or
production actions. Uninstall and integration activation require an existing
one-time approval. Updates retain the installed version and rollback metadata.

## Integration wizard

Supported adapters are Telegram, Email, Google, Slack, GitHub, Webhook, and API
Key. The API accepts a protected secret reference only. Raw credentials are
rejected and are never stored in package metadata, task state, logs, or browser
storage.

## Developer portal and monetization

The existing Creator/Marketplace publishing pipeline remains the authority for
creating and validating packages. `/developer` adds a consolidated view of
owned packages, versions, installs, reviews, and estimated earnings. Payments
remain disabled; revenue share and the default 15 percent marketplace
commission are accounting metadata only.

Plans available to new deployments are Free, Starter, Pro, Team, Business, and
Enterprise. Existing plan identifiers and subscriptions remain valid.

## Enterprise isolation

`PUBLIC`, `ORGANIZATION`, and `PRIVATE` visibility are enforced by owner and
organization scope. Private agents, skills, and workflows cannot be installed
outside their tenant. All reads and lifecycle actions require authentication,
authorization, rate limiting, request/correlation IDs, and audit.

## Operations

Dashboard routes:

- `/marketplace`
- `/marketplace/workflows`
- `/marketplace/skills`
- `/marketplace/item/{id}`
- `/ai-team`
- `/developer`

Public API routes are documented in `api/schemas/openapi-v1.yaml`. Production
operators should migrate to schema 13 before starting updated application
services. Gateway configuration is unchanged.
