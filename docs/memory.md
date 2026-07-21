# Agent Memory 2.0

Memory scopes are `PERSONAL`, `WORKSPACE`, and `AGENT`. Every read and write checks actor identity, active tenant membership, RBAC, workspace, scope, and optional agent identity. Keys are stored as peppered hashes and values are encrypted at rest with a Fernet key derived from a protected service secret; audit events contain metadata only, not memory values. The protected secret source stays outside Git.

Memory is not a secret store. Tokens, credentials, private keys, and production configuration must never be inserted.
