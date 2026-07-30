# Files and Artifacts

Nexora 4.5 adds a private result-file layer without exposing the host
filesystem or OpenClaw Gateway.

## User flow

1. A workspace task reaches `COMPLETED`.
2. Nexora generates Markdown and JSON result artifacts.
3. Open `/artifacts` to filter by task, preview text, or download a file.
4. Task and Workbench details also show their related files.
5. The existing Telegram owner receives the Markdown result.

## Storage and integrity

Artifacts live below the existing private runtime state root. Paths are
constructed exclusively from validated owner, workspace, task and artifact
identifiers. Files use mode `0600`; directories use `0700`. Writes use a
private temporary file, flush, `fsync`, atomic replace, final mode validation,
and SHA-256 verification on read.

Only platform-generated Markdown and JSON are enabled. An artifact is limited
to 2 MiB. Symlinks, path traversal, executable formats, arbitrary uploads and
host paths are rejected.

## Access control

The Dashboard endpoints require an authenticated session, `artifacts:read`,
active workspace membership, tenant isolation, rate limiting and audit:

- `GET /api/artifacts`
- `GET /api/artifacts/{artifact_id}`
- `GET /api/artifacts/{artifact_id}/download`

Artifact creation and download produce safe audit events. API responses never
contain the owner namespace or physical storage path.

## Operations

Artifact generation is idempotent for the same task, format and checksum.
Dashboard startup safely backfills completed tasks that predate v4.5.
Artifact delivery failure does not change a successfully completed task.

No database migration is required. Rollback to v4.4 leaves generated files
untouched below the runtime state root, where the older release ignores them.
