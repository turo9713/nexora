# Security model

Nexora applies deny-by-default at every ingress and execution boundary.

## Authentication and isolation

- Telegram requires an exact private owner allowlist; unknown users receive
  only `ACCESS_DENIED` and cannot create state or invoke an LLM.
- Dashboard uses scrypt password hashes, expiring signed sessions, brute-force
  controls, CSRF protection, secure cookies, and audited login events.
- Public API keys are shown once, stored only as scrypt hashes, expire, and
  carry explicit scopes. Missing scopes deny access.
- Owner namespaces are HMAC-derived; raw Telegram IDs are excluded from state.

## Execution policy

Policy Engine checks agent state, tool allowlist, canonical workspace path,
risk, action type, and one-time approval. Root, secret extraction, Docker,
SSH/firewall changes, financial actions, sandbox changes, and policy mutation
are forbidden. Skills are validated declarative metadata, not executable code.

## Approvals and audit

Risky actions use a random approval ID bound to task, owner session, expiration,
and single use. Cancellation invalidates pending approvals. Events and audit
records are bounded and redacted before persistence; Authorization headers,
cookies, tokens, passwords, connection strings, private keys, and context are
removed.

## Container isolation

Release containers run as UID/GID 10001, with read-only root filesystems,
`no-new-privileges`, all capabilities dropped, temporary filesystems for `/tmp`,
and no privileged mode, host network, or Docker socket. Dashboard/API ports
bind to host localhost by default. Release Compose contains no OpenClaw service
and therefore cannot publish its Gateway.

## Secret storage

`.env.example` contains empty placeholders only. The installer generates
protected local secret files (directory `700`, files `600`) mounted read-only
through Compose secrets. Secrets are ignored by Git and excluded from release
archives. Run `scripts/secret-scan.sh` before every commit and release.

## Threat limitations

Local root and Docker daemon access remain equivalent to full host control.
Public exposure requires a separately reviewed TLS proxy, network policy, and
operational monitoring. The demo is offline and never publishes content.
