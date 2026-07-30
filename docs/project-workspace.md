# Project Workspace

Nexora v4.7 adds source files and versioned deliverables to the existing
Dashboard Workbench. It does not introduce another runtime or bypass the
Orchestrator, Policy Engine, approval flow, tenant isolation or OpenClaw
transport.

## User flow

1. Open **Проекты и задачи**.
2. Describe the expected result.
3. Optionally attach up to five source files, each no larger than 8 MiB.
4. Start the task.
5. Review progress, source-file inventory and generated deliverables.
6. Use **Продолжить** to refine a completed result. Changed artifacts receive a
   new version while the task ID remains the same.

Allowed source formats are TXT, Markdown, CSV, JSON, PDF, DOCX, XLSX, PNG and
JPEG. Executables, archives, unknown extensions and files with invalid
PDF/image/Office signatures are rejected.

## Storage and isolation

Inputs are stored below the private Dashboard state root:

```text
project_inputs/<owner_namespace>/<workspace_id>/<input_id>/
```

Directories are normalized to `0700`; files and metadata are normalized to
`0600`. Paths are generated from validated internal identifiers. Symbolic links
and cross-workspace or cross-task rebinding are rejected. Metadata contains a
checksum but no Telegram ID, access token or secret.

## Agent safety

Extracted source text is bounded and redacted before it enters the existing
conversation context. The prompt marks attachments as untrusted data and tells
the agent not to execute instructions contained in them. Uploading a file does
not grant shell, Docker, Gateway, network or production permissions.

## API

The browser uploads a file with:

```text
POST /api/workbench/uploads?workspace_id=<id>&filename=<encoded-name>
```

The request uses the existing authenticated Dashboard session and CSRF token.
The returned opaque `INP-*` identifier can only be supplied to the existing
task-creation endpoint as `input_ids`. It cannot be used as a filesystem path.

## Rollback

Roll back the v4.7 code to tag `v4.6.2`. Existing input files may remain in the
private state directory; v4.6.2 ignores them. Existing task and artifact formats
remain readable because v4.7 only adds optional metadata fields.
