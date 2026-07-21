# Docker image strategy

Nexora prepares three role images:

- `nexora/runtime`
- `nexora/dashboard`
- `nexora/api`

For v2.0.0 all roles use the same reviewed source image with a role-specific OCI
label and service command supplied by Compose. The release workflow builds all
three images but deliberately uses no registry login and performs no push.

Before future publication, add SBOM, provenance, signature verification, and a
separate approval for registry credentials. Every runtime service must remain
non-root, read-only, capability-free, health-checked, and without Docker socket.
