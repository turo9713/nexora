# Dashboard API

This document covers the internal Dashboard API. The external versioned facade
is described in `public-api.md` and its OpenAPI document is
`api/schemas/openapi-v1.yaml`.

All `/api/*` endpoints except `/api/login` require a valid signed server-side
session. Mutating endpoints also require an exact same-origin request and the
session CSRF token.

## Authentication

- `POST /api/login`
- `GET /api/session`
- `POST /api/logout`

## Platform

- `GET /api/health`
- `GET /api/tasks?status=&search=&limit=`
- `GET /api/tasks/{id}`
- `GET /api/agents`
- `GET /api/agents/{id}`
- `POST /api/agents/{id}/actions` with `enable`, `disable`, or `reload`
- `GET /api/skills`
- `GET /api/skills/{id}`
- `POST /api/skills/{id}/enable`
- `POST /api/skills/{id}/disable`
- `POST /api/skills/{id}/reload`
- `GET /api/approvals?status=`
- `POST /api/approvals/{id}/approve`
- `POST /api/approvals/{id}/reject`
- `GET /api/audit?date=&severity=&source=&event=&limit=`
- `GET` and `POST /api/platform/api-keys`
- `POST /api/platform/api-keys/{id}/disable|delete`
- `GET` and `POST /api/platform/webhooks`
- `POST /api/platform/webhooks/{id}/disable|delete`
- `GET /api/platform/metrics`
- `GET /api/platform/integrations`

The task and approval queries are constrained by the protected HMAC owner
namespace. Missing and foreign task IDs return the same `404` response. API
responses contain safe summaries, not raw context or logs.

Skill mutations return `202 WAITING_APPROVAL`; lifecycle state changes only
after the existing Approval Center accepts a valid one-time approval.
API key and webhook mutations follow the same approval path. Newly generated
credentials appear only in that approval response and are never persisted.

## External API summary

- `POST /api/v1/tasks` (`tasks:create`)
- `GET /api/v1/tasks` and `/api/v1/tasks/{id}` (`tasks:read`)
- `GET /api/v1/agents` (`agents:read`)
- `GET /api/v1/skills` (`skills:read`)
- `GET` and `POST /api/v1/webhooks` (`webhooks:manage`)

Keys use the `nx_live_` prefix, are displayed once, and are stored as hashes.
Requests receive a request ID and correlation ID, owner and scope checks, per
key/owner/endpoint rate limits, sanitized audit, and bounded response bodies.
Webhook destinations must be public HTTPS endpoints and deliveries are signed.
