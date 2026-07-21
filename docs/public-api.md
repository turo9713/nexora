# Nexora Public API v1

## Nexora 2.1 community endpoints

- `GET /api/v1/templates` requires `templates:read`.
- `GET /api/v1/templates/{id}` requires `templates:read`.
- `POST /api/v1/templates/{id}` requires `templates:install`; medium-risk templates return `WAITING_APPROVAL`.
- `GET /api/v1/playground/examples` requires `playground:read`.

Authentication, owner isolation, rate limiting, Policy Engine checks, redacted audit events, request IDs, and deny-by-default scopes apply to these endpoints. Playground returns metadata only and cannot execute a task.

## Nexora 2.2 team endpoints

- `GET /api/v1/organizations` requires `organizations:read`.
- `GET /api/v1/workspaces` requires `workspaces:read`.
- `POST /api/v1/workspaces` requires `workspaces:write` and organization RBAC.
- `GET /api/v1/members?workspace_id=...` requires `members:read`.
- `POST /api/v1/invite` requires `members:invite`, workspace RBAC, and a matching one-time approval.
- `GET /api/v1/knowledge?workspace_id=...` requires `knowledge:read`.
- `POST /api/v1/knowledge` requires `knowledge:write`.

Tasks may include `workspace_id`. Agent and skill listing may use the same query
parameter to return only components assigned to that workspace. Tenant IDs are
never authorization credentials; membership and RBAC are checked independently.

The API is a separate process and authenticated facade over TaskService,
Agent Registry, Skill Registry, Policy Engine, approvals, and owner-isolated
repositories. It does not import OpenClawProvider or OpenClawTransport and has
no Gateway credential.

Production staging endpoint: `https://127.0.0.1:18881/api/v1/`.

Endpoints:

- `POST /api/v1/tasks` (`tasks:create`, 10/minute);
- `GET /api/v1/tasks` and `/api/v1/tasks/{id}` (`tasks:read`);
- `GET /api/v1/agents` (`agents:read`);
- `GET /api/v1/skills` (`skills:read`);
- `GET` and `POST /api/v1/webhooks` (`webhooks:manage`).

Every request returns `X-Request-ID` and `X-Correlation-ID`. Audit records
contain method, route, safe IDs, and result but never Authorization or key data.

Create an API key from Dashboard -> API Keys. Select the minimum scopes, approve
the request, and copy the `nx_live_*` value from the one-time response. Rotation
means creating and testing a new key, then disabling the old one through another
approval. A deleted or expired key cannot authenticate.

Example from the VPS without putting a key in shell history:

```bash
read -rsp 'API key: ' NEXORA_API_KEY; echo
curl --fail --silent --show-error --cacert /path/to/trusted-api-ca.pem \
  -H "Authorization: Bearer $NEXORA_API_KEY" \
  https://127.0.0.1:18881/api/v1/tasks
unset NEXORA_API_KEY
```
