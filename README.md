# Nexora

**Self-hosted AI Agent Platform** — a security-first runtime for tasks, agents, declarative
skills, approvals, audit events, a web dashboard, and a scoped public API.

Nexora 3.4.2 adds private atomic task storage and workspace-bound Telegram
realtime events to the tenant-scoped operations experience on top of the read-only
Task Control Center: a user home, Server-Sent Event task updates, activity,
notifications, workspace and agent status views, analytics, and safe onboarding.
The repository contains the open-source
platform core and safe examples. Production configuration, credentials,
customer data, private integrations, commercial skills, and VPS automation are
deliberately outside the public boundary.

## Features

- Task lifecycle, workflow routing, progress, cancellation, and idempotency.
- Read-only Task Control Center with safe lifecycle timelines and no UI mutations.
- User operations dashboard with workspace metrics, activity feed, notifications,
  agent status, analytics, and event-driven task updates.
- Eight deny-by-default agent manifests and a policy gate before execution.
- Read-only Agent Control Center with task counts and last activity; no UI mutation controls.
- Declarative, schema-validated skills; no arbitrary plugin code loading.
- One-time, expiring approvals for risky operations.
- Sanitized event and tamper-evident audit records.
- Owner-isolated Telegram adapter, authenticated dashboard, and scoped API keys.
- SQLite storage with reversible migrations and retained JSON compatibility.
- Signed HTTPS webhooks, read-only GitHub integration, and safe content drafts.
- Declarative workflow templates with owner-isolated, reversible installation.
- A data-only Playground and review-first Community Skills contribution flow.
- Fail-closed multi-tenant organizations and workspaces with OWNER, ADMIN,
  MANAGER, OPERATOR, and VIEWER roles.
- Workspace-isolated knowledge, agents, skills, tasks, comments, and audit activity.
- Read-only tenant billing views with Free, Pro, Team, and Enterprise plans.
- Server-side usage metering and pre-mutation limits enforcement.
- Approval-only plan changes and organization blocking; no payment processor.
- Verified publishers, checksum-protected packages, tenant-isolated installs,
  reviews, and community-license metadata with no automatic code execution.
- Owner-isolated creator profiles, immutable package releases, trusted-creator
  verification, quality scoring, and privacy-preserving creator analytics.
- Approval-gated custom Agent Manifest v2 creation and immutable versions.
- Workspace-scoped Agent Teams, policy-checked plans, three-level memory, and evaluations.
- Marketplace packages for single agents, agent teams, and AI departments.
- In-process Python SDK with no arbitrary code execution or Gateway credential.

## Architecture

```text
Users
  |
Dashboard / API / Telegram
  |
Nexora Core
  |
Agents + Skills
  |
OpenClaw Runtime
```

The browser never talks to OpenClaw, SQLite, or a shell directly. The public API
does not contain a provider/Gateway token. See [docs/architecture.md](docs/architecture.md)
and [core/README.md](core/README.md).

## Installation

Requirements: Linux, Docker Engine, Docker Compose v2, Python 3, OpenSSL, and
curl. Clone the repository, then run:

```bash
git clone https://github.com/turo9713/nexora.git
cd nexora
cp .env.example .env
sudo ./install.sh
```

The installer creates local protected secret files, builds four non-root
containers, validates Compose, waits for health checks, and prints the local
Dashboard URL. Dashboard and API bind to `127.0.0.1` by default. Use an SSH
tunnel for remote administration; do not publish OpenClaw Gateway.

For manual deployment:

```bash
cp .env.example .env
sudo python3 scripts/generate-release-secrets.py
docker compose -f docker-compose.release.yml config --quiet
docker compose -f docker-compose.release.yml up -d --build
```

Do not put real secrets in Compose, source code, Git, documentation, or image
layers. The release Compose uses read-only secret mounts under `/run/secrets`.

The installer itself requires root only to set host secret-file ownership to
the fixed non-root container UID. Every long-running container remains UID
10001 and has no elevated capability.

## Quick Start

After signing in, open **Главная** (`/home`) for the current workspace summary,
activity, notifications, and realtime connection state. Open **Tasks** to inspect your task list, current runtime
progress, safe details, and lifecycle timeline. Task Control Center is strictly
read-only: start, continuation, approval, and cancellation stay on the existing
authorized runtime surfaces. Telegram remains available as an independent
dialogue surface.

Open the Dashboard URL from the installer and sign in with the one-time password
shown during installation. Run the offline, non-publishing demo:

```bash
python3 examples/demo_content_workflow.py
```

The demo models `Research -> Content -> QA -> Approval -> Result`; it performs
no network request and no production action.

See [Getting Started](docs/getting-started.md) for health checks and safe local
access.

## User Operations (v3.4)

The Dashboard exposes `/home`, `/activity`, `/notifications`, `/workspace`,
`/agents/status`, `/analytics`, and `/onboarding`. Task updates use authenticated
same-origin Server-Sent Events with automatic reconnect and workspace filtering;
the browser does not poll the task API continuously. Operational pages are read
projections and never call tools, shell, Docker, or OpenClaw. The only local UI
write is CSRF-protected notification read state.

Scoped API keys can read `GET /api/v1/dashboard`, `GET /api/v1/activity`,
`GET /api/v1/notifications`, and `GET /api/v1/agents/status` through the same
RBAC, tenant, rate-limit, request/correlation ID, and audit controls. See
[User Dashboard](docs/user-dashboard.md), [Realtime](docs/realtime.md),
[Notifications](docs/notifications.md), and [Operations](docs/operations.md).

## Project Workspace & Deliverables (v4.7.0)

The authenticated Workbench accepts up to five source files for a task
(`TXT`, `MD`, `CSV`, `JSON`, `PDF`, `DOCX`, `XLSX`, `PNG`, `JPG`). Inputs are
stored privately and bound to the current owner, workspace and task. Textual
content is passed to the existing runtime as untrusted reference data; binary
files remain safely inventoried when deterministic extraction is unavailable.

Continue a completed task from its result page to create the next deliverable
version without creating a second task. The task card displays source files and
versioned download links. See
[Project Workspace](docs/project-workspace.md).

## Files and Artifacts (v4.6.2)

Completed tasks produce private Markdown, JSON, DOCX and PDF result artifacts. The
authenticated `/artifacts` page lists files only from the active workspace,
supports safe text preview and download, and links them from task details.
Spreadsheet/analytics requests also produce XLSX, while explicit archive or
file-set requests produce ZIP. DOCX and PDF preserve headings, lists and tables;
XLSX separates summary, structured data and recommendations. The Telegram owner
receives every generated rich document with a format-specific caption.
Artifacts are stored with checksum verification, `0600` file permissions and
`0700` directories. Office files are macro-free and have no external
relationships; PDFs contain no active actions. Executable uploads and
user-selected host paths are not supported. See
[Files and Artifacts](docs/artifacts.md).

## Templates and Playground

Use the authenticated Dashboard sections `/templates` and `/playground`, or the
scoped `/api/v1/templates` and `/api/v1/playground/examples` endpoints. Templates
cannot add permissions; medium-risk templates wait for an existing one-time
approval. See [templates](docs/templates.md), [Playground](docs/playground.md),
and [community skills](docs/community-skills.md).

## Teams and Workspaces

Organizations contain isolated workspaces. Every access is resolved through the
authenticated user, organization, workspace membership, RBAC decision, Policy
Engine, and resource repository. Cross-workspace and cross-organization lookups
fail closed. Membership and capability changes require an existing one-time
approval. See [teams](docs/teams.md), [workspaces](docs/workspaces.md),
[roles](docs/roles.md), [knowledge base](docs/knowledge-base.md), and
[multi-tenancy security](docs/security-multitenancy.md).

## Cloud and Billing Foundation

Organizations receive a Free subscription lazily and may be assigned another
plan only through the protected Admin Console approval flow. Usage events accept
only trusted runtime sources and are immutable. Public clients can read their
own plan, usage, and limits but cannot modify billing state. Cloud provisioning
creates tenant metadata only; it allocates no external infrastructure and makes
no charge. See [billing](docs/billing.md), [plans](docs/plans.md),
[usage](docs/usage.md), and [cloud architecture](docs/cloud-architecture.md).

## Marketplace

The authenticated Dashboard exposes `/marketplace`, `/my-items`, and
`/publisher`. Scoped clients use `GET /api/v1/marketplace`,
`GET /api/v1/marketplace/{id}`, `POST /api/v1/marketplace/{id}/install`, and
`POST /api/v1/marketplace/publish`. Packages contain validated manifests only;
Nexora neither downloads nor executes publisher code. Medium/high-risk installs
and integrations require the existing one-time approval flow. See
[Marketplace](docs/marketplace.md), [publishing](docs/publishing.md),
[package format](docs/package-format.md), and
[Marketplace security](docs/security-marketplace.md).

## Creator Economy

The authenticated `/creator` Dashboard contains My Packages, Analytics, Reviews,
Verification, and Settings views. Public API clients can read sanitized profiles
with `creators:read`; private package and analytics endpoints require
`creator:read` and resolve the owner from the API key. Package publication still
passes the existing Marketplace validator and immutable checksum controls.
Verification, suspension, archive, and rollback are administrative actions that
require Policy Engine authorization, an exact one-time approval, and an audit
event. See [Creator Guide](docs/creator-guide.md), [Creator Analytics](docs/analytics.md),
[Verification](docs/verification.md), and [Publishing](docs/publishing.md).

## AI Agent Ecosystem

Use `/agent-center`, `/agent-teams`, `/agent-memory`, `/agent-planning`,
`/agent-evaluations`, and `/sdk` in the authenticated Dashboard. Public API
clients use the matching `/api/v1/agent-*` endpoints with explicit
`agent_ecosystem:read` or `agent_ecosystem:manage` scopes. Agent and team
mutations consume one-time approvals; plans are proposals and never execute by
themselves. See [Agent Builder](docs/agent-builder.md), [Agent Teams](docs/agent-teams.md),
[Memory 2.0](docs/memory.md), [Planning](docs/planning.md), [SDK](docs/sdk.md),
and [Agent Security](docs/agent-security.md).

## Security

Nexora is deny-by-default. Agents and skills cannot grant themselves new tools,
read secrets, use Docker, obtain root, or bypass approvals. Release containers
run non-root with a read-only root filesystem, all Linux capabilities dropped,
`no-new-privileges`, no Docker socket, and only documented writable volumes.

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
Never include credentials, private user content, or production identifiers.

## Agents

The registry loads reviewed manifests for Orchestrator, Developer, Content,
Research, Analytics, QA, DevOps, and Sales. Unknown or disabled agents fail
closed. See [docs/agents.md](docs/agents.md).

## Skills

Skills are declarative manifests validated against a pinned JSON Schema. Shell,
production, secret, root, and Docker access are forbidden. See
[docs/skills.md](docs/skills.md) and [docs/skill-development.md](docs/skill-development.md).

## API

The versioned `/api/v1` facade supports owner-scoped tasks, agents, skills, and
approval-gated webhooks. API keys are shown once and stored only as scrypt
hashes; scopes default to deny-all. See [docs/api.md](docs/api.md).

## Enterprise Operations (v3.5)

The Enterprise layer adds a tenant-scoped Security Center, approval-gated and
versioned policies, immutable security events, SLA metrics, storage health, and
validated deployment profiles. The SSO layer is foundation-only: SAML, OIDC,
and OAuth adapters are disabled and production authentication is unchanged.

Dashboard routes are `/security-center`, `/policies`, `/sla`,
`/storage-health`, and `/enterprise`. Public API reads require the explicit
`enterprise:read` scope. See [docs/enterprise.md](docs/enterprise.md) and
[docs/policies.md](docs/policies.md).

## AI Workforce Marketplace (v4.0)

Install validated AI employees, workflow packs, and skills from the
authenticated Marketplace without editing YAML. One-click installation creates
tenant-scoped memory, permission, prompt, workflow, setting, and workspace
bindings; it never executes arbitrary package code. Use `/marketplace`,
`/marketplace/workflows`, `/marketplace/skills`, `/ai-team`, and `/developer`.

Integrations accept protected secret references only and activate through the
existing one-time approval flow. OpenClaw Gateway remains private and is never
called by Dashboard frontend or Marketplace APIs. See
[AI Workforce Marketplace](docs/ai-workforce-marketplace.md),
[v4 architecture and ER diagram](docs/architecture-v4.md), and
[deployment and rollback](docs/deployment-v4.md).

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r runtime/requirements.txt
python -m pytest -q
bash scripts/secret-scan.sh
docker compose -f docker-compose.release.yml config --quiet
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [docs/development.md](docs/development.md),
and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Roadmap

- **v4.1:** signed package provenance, staged tenant rollouts, compatibility
  preview, and administrator-controlled update channels.
- **v4.2:** integration health observability and portable workforce bundles.
- **v5.0:** optional managed control plane while preserving self-hosting.

## Release and rollback

CI validates tests, secret/history scans, dependencies, Compose hardening, and
release artifacts. `scripts/rollback-release.sh --check v1.8.0` validates the
rollback target; execution creates a Git bundle before switching versions.
Production deployment remains an administrator-controlled operation.

For the first public GitHub repository, import the verified source archive into
a new empty repository. Do not push private local branches or all local tags.
See [docs/publication.md](docs/publication.md).

Licensed under the [MIT License](LICENSE).
