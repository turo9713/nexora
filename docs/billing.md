# Billing foundation

Nexora 2.3 provides billing state and quota enforcement without connecting a
payment processor. Each organization has one current subscription. New tenant
reads lazily create an `ACTIVE` Free subscription; lifecycle states are
`TRIAL`, `ACTIVE`, `PAUSED`, `CANCELLED`, and `EXPIRED`.

External API access is read-only:

- `GET /api/v1/plans` with `plans:read`;
- `GET /api/v1/subscription?organization_id=...` with `billing:read`;
- `GET /api/v1/usage?organization_id=...` with `usage:read`;
- `GET /api/v1/limits?organization_id=...` with `limits:read`.

Every tenant endpoint independently verifies organization membership. Missing
and foreign organization identifiers return the same unavailable response.

Changing a plan or blocking an organization is available only to the protected
Dashboard admin namespace. The change creates a normal Nexora management task,
requires an exact expiring one-time approval, passes Policy Engine again during
execution, and writes immutable billing plus redacted audit events. No endpoint
accepts card data, money amounts, invoices, or payment credentials.
