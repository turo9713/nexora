# Skills security model

Skills are denied by default and cannot expand an agent's existing authority.
Effective permission is the intersection of Agent Policy, skill manifest,
sandbox, requested tool, requested path, and network mode.

Hard denials:

- arbitrary code, entrypoints, commands, install scripts, or shell;
- root, sudo, production changes, Docker socket, or container control;
- `.env`, `/etc`, `/root`, `/run/secrets`, tokens, credentials, or API keys;
- paths outside the declared workspace scope;
- unrestricted network access or a tool absent from the manifest;
- unknown, disabled, invalid, incompatible, or unsandboxed skills.

Manifest schema uses `additionalProperties: false`. Validation fails closed with
`SKILL_VALIDATION_FAILED`; a previously registered invalid skill is marked
`FAILED`. Dashboard APIs require authentication, authorization, exact Origin,
CSRF, rate limits, and audited one-time approvals. API responses omit manifest
paths, hashes, raw logs, secrets, and private runtime context.

The Dashboard container remains non-root, read-only, capability-free, without
Docker socket or Gateway/Telegram credentials. The Gateway remains localhost
only and is not involved in skill management.
