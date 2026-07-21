# Teams

Nexora 2.2 introduces organizations as the top-level tenant. An organization
owns one or more workspaces; users gain access only through an active workspace
membership. External identities are represented by a one-way namespace or an
email hash. Passwords, Telegram tokens, and other credentials are never stored
in team records.

## Lifecycle

Organizations use `ACTIVE`, `SUSPENDED`, and `ARCHIVED`. Suspended or archived
organizations deny resource access. Archiving is restricted to OWNER and
consumes an exact, unexpired, one-time approval.

Member invitations, role changes, removals, and workspace agent/skill changes
follow `Policy Engine -> Approval -> Database transaction -> Audit`. Replayed or
mismatched approvals fail closed.

## API

- `GET /api/v1/organizations` requires `organizations:read`.
- `GET /api/v1/members?workspace_id=...` requires `members:read`.
- `POST /api/v1/invite` requires `members:invite` and a matching approval.

The Dashboard mirrors these owner-scoped views at `/organizations` and
`/members`. It never exposes raw external identity hashes.
