# Workspace knowledge base

Knowledge documents contain instructions, approved documents, company style,
rules, and templates for one workspace. Supported access levels are `TEAM`,
`MANAGERS`, and `ADMINS`; listing is filtered by the current member role.

Documents are validated and bounded before storage. Content resembling API
keys, authorization values, passwords, private keys, connection strings, or
environment secrets is rejected. A SHA-256 content digest supports integrity
checks, but is not an authentication credential.

Knowledge is available through authenticated endpoints:

- `GET /api/v1/knowledge?workspace_id=...` with `knowledge:read`;
- `POST /api/v1/knowledge` with `knowledge:write`.

The frontend never reads SQLite directly. Upload and read operations pass
workspace membership, RBAC, service validation, and audit. Embedding generation
is intentionally not enabled in 2.2; `embeddings/` is reserved for a later,
reviewed design that preserves the same tenant boundary.
