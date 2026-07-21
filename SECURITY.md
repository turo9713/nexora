# Security Policy

## Supported versions

Security fixes are provided for the latest stable `2.x` release. Older tags are
retained for audit and rollback but may not receive fixes.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Contact the project
maintainers through the private security-reporting channel configured on the
future repository. Until that channel is published, keep the report private and
do not share exploit code, credentials, customer data, or production addresses.

Include the affected version, impact, minimal reproduction, and recommended
mitigation. Never include real API keys or tokens. Maintainers should acknowledge
a report within seven days and coordinate disclosure after a fix is available.

## Security invariants

- OpenClaw Gateway remains private and is never exposed by release Compose.
- Authentication, owner isolation, policy checks, and approvals are mandatory.
- Secrets are files or external secret references, never tracked configuration.
- Skills are declarative metadata and cannot execute arbitrary code.
- Dashboard/API containers do not receive Docker socket, root, or Gateway token.
