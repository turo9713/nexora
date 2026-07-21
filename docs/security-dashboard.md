# Dashboard security

## Authentication and sessions

- scrypt password hashes with per-password salt;
- random signed server-side session identifiers;
- 30-minute session expiration;
- brute-force lockout after repeated failures;
- Secure, HttpOnly, SameSite=Strict host cookie;
- login, session, expiration, and logout audit events.

## Request security

- exact Origin validation and per-session CSRF token on mutations;
- deny-by-default permissions;
- rate limiting and bounded JSON bodies;
- CSP, HSTS, frame denial, MIME sniffing denial, no-referrer, and restrictive
  browser permissions policy;
- parameterized SQL and owner namespace filters protect against IDOR.

## Container security

- localhost-only published port;
- non-root numeric UID/GID;
- read-only root filesystem and project mount;
- only runtime state is writable;
- all Linux capabilities dropped;
- `no-new-privileges` enabled;
- no Docker socket, Gateway secret, Telegram token, or host network;
- isolated Docker bridge not shared with the Gateway.

Agent changes pass the v1.5 Policy Engine and the existing ApprovalService. The
dashboard cannot directly execute shell commands or invoke OpenClaw.
Skill Enable, Disable, and Reload use that same approval path; the Dashboard
cannot install or execute plugin code.
