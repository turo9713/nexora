# Nexora

**Self-hosted AI Agent Platform** — a security-first runtime for tasks, agents, declarative
skills, approvals, audit events, a web dashboard, and a scoped public API.

Nexora 2.4 adds a security-reviewed Marketplace foundation for declarative,
versioned Agents, Skills, Templates, and Integrations. The repository contains the open-source
platform core and safe examples. Production configuration, credentials,
customer data, private integrations, commercial skills, and VPS automation are
deliberately outside the public boundary.

## Features

- Task lifecycle, workflow routing, progress, cancellation, and idempotency.
- Eight deny-by-default agent manifests and a policy gate before execution.
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

Open the Dashboard URL from the installer and sign in with the one-time password
shown during installation. Run the offline, non-publishing demo:

```bash
python3 examples/demo_content_workflow.py
```

The demo models `Research -> Content -> QA -> Approval -> Result`; it performs
no network request and no production action.

See [Getting Started](docs/getting-started.md) for health checks and safe local
access.

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

- **v2.5:** expanded publisher trust and signed package provenance.
- **v2.7:** curated integration bundles.
- **v3.0:** optional managed cloud platform while preserving self-hosting.

## Release and rollback

CI validates tests, secret/history scans, dependencies, Compose hardening, and
release artifacts. `scripts/rollback-release.sh --check v1.8.0` validates the
rollback target; execution creates a Git bundle before switching versions.
Production deployment remains an administrator-controlled operation.

For the first public GitHub repository, import the verified source archive into
a new empty repository. Do not push private local branches or all local tags.
See [docs/publication.md](docs/publication.md).

Licensed under the [MIT License](LICENSE).
