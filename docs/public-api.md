# Nexora Public API v1

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
