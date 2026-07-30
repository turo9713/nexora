# Files and Artifacts

Nexora 4.6.2 extends the private result-file layer without exposing the host
filesystem or OpenClaw Gateway.

## User flow

1. A workspace task reaches `COMPLETED`.
2. Nexora generates Markdown, JSON, DOCX and PDF result artifacts.
3. Open `/artifacts` to filter by task, preview text, or download a file.
4. Task and Workbench details also show their related files.
5. The existing Telegram owner receives every generated rich document with a
   short format-specific caption.

## Storage and integrity

Artifacts live below the existing private runtime state root. Paths are
constructed exclusively from validated owner, workspace, task and artifact
identifiers. Files use mode `0600`; directories use `0700`. Writes use a
private temporary file, flush, `fsync`, atomic replace, final mode validation,
and SHA-256 verification on read.

Only platform-generated, allowlisted non-executable formats are enabled. An
artifact is limited to 10 MiB. Symlinks, path traversal, executable formats,
arbitrary uploads and host paths are rejected.

## Rich document formats

Every completed task produces:

- Markdown for portable plain-text use;
- JSON for machine-readable integration;
- DOCX using the Nexora business-brief style;
- PDF with an embedded Cyrillic-capable DejaVu Sans font.

DOCX and PDF preserve detected headings, lists, key-value fields and Markdown
tables. Requests that explicitly concern spreadsheets, tables, budgets,
metrics, analytics or finance also produce a three-sheet XLSX workbook:
`Сводка`, `Данные` and `Рекомендации`. Requests for an archive, project file
set or source bundle also produce ZIP with a human-readable `README.txt` and
`MANIFEST.json` checksums.

All renderers run in memory and receive only the redacted task title/result.
DOCX/XLSX packages are rejected if they contain executable members or external
relationships. XLSX contains no formulas or macros. PDF is rejected if active
JavaScript or launch actions are detected. ZIP members use a fixed allowlist;
user-provided paths are never accepted.

The Dashboard previews only Markdown and JSON. Binary formats show metadata and
must be downloaded through the authenticated, workspace-scoped endpoint.
Telegram sends all generated rich document formats and uses Markdown as a
fallback when no binary artifact is available.

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
