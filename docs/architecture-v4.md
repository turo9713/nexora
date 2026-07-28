# Nexora 4.0 Architecture

## Request flow

```mermaid
flowchart TD
    C[Dashboard / Public API] --> A[Authentication + scopes]
    A --> T[Organization and workspace isolation]
    T --> P[Policy Engine]
    P --> M[Marketplace validation]
    M --> R[AI Workforce Service]
    R --> I[Declarative installer]
    I --> W[Workspace bindings and resources]
    W --> E[Existing Nexora runtime]
    E --> O[OpenClaw Provider]
    P --> Q[Approval Engine]
    R --> U[Audit / analytics / notifications]
```

The browser never accesses OpenClaw, SQLite, secrets, or tools directly. AI
employees are bundles of existing Marketplace entities and declarative
workspace resources rather than executable plugins.

## Entity relationship diagram

```mermaid
erDiagram
    ORGANIZATIONS ||--o{ WORKSPACES : owns
    WORKSPACES ||--o{ WORKFORCE_INSTALLATIONS : receives
    MARKETPLACE_ITEMS ||--o{ MARKETPLACE_METADATA : describes
    MARKETPLACE_ITEMS ||--o{ WORKFORCE_INSTALLATIONS : installed_as
    WORKFORCE_INSTALLATIONS ||--o{ WORKFORCE_RESOURCES : provisions
    WORKFORCE_INSTALLATIONS ||--o{ INTEGRATION_WIZARDS : configures
    PUBLISHERS ||--o{ MARKETPLACE_ITEMS : publishes
    PUBLISHERS ||--o{ MARKETPLACE_EARNINGS : accrues
    PLANS ||--o{ SUBSCRIPTIONS : selected_by
    ORGANIZATIONS ||--o{ SUBSCRIPTIONS : has
```

`marketplace_metadata` adds presentation, compatibility, pricing, visibility,
auto-update preference, and documentation fields without changing the legacy
Marketplace table. `workforce_resources` stores only declarative resource
payloads. Protected credential values remain in the existing secret store.

## Compatibility

- Existing Marketplace `AGENT`, `SKILL`, and `TEMPLATE` IDs are unchanged.
- Existing task/runtime, Agent Registry, Skills, Billing, Memory, RBAC, and
  approval APIs are unchanged.
- Migration 013 is additive and reversible.
- No Gateway, firewall, port, secret, or production authentication change is
  required.
