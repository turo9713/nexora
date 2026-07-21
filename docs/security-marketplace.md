# Marketplace security

Marketplace is deny-by-default. `shell`, `root`, `secret_access`,
`docker_access`, `production_access`, executable code, entrypoints, scripts,
hooks, environment values, and Docker/container definitions are rejected.
Every manifest must enable sandboxing.

Canonical JSON is hashed with SHA-256. Packages and marketplace events are
immutable in SQLite. Installation recomputes the checksum and reruns validation
before Policy Engine evaluation. The optional `sha256:<digest>` attestation
detects accidental or malicious content mismatch; it is an integrity
foundation, not publisher identity PKI.

Workspace membership and RBAC are checked on install, list, rollback, and
review operations. Cross-tenant resources return a generic unavailable result.
Reviews require an active installation and are limited to one per user per
package version. No payment handling exists in v2.4.
