# Dashboard setup and use

The production service is `nexora-dashboard`. Docker publishes its TLS port
only on VPS localhost: `127.0.0.1:18880`. It is intentionally not attached to
the Gateway network and has no Gateway credentials.

## Access

Create an SSH tunnel from a trusted computer:

```bash
ssh -L 18880:127.0.0.1:18880 root@your-vps
```

Open `https://127.0.0.1:18880`. The local certificate is self-signed, so the
browser will require an explicit local trust decision. Do not expose this port
through public DNS or a public reverse proxy.

## Password

Set or rotate the password interactively:

```bash
/workspace/nexora/scripts/set-dashboard-password.sh
```

The script disables terminal echo, confirms the password, hashes it with
scrypt, atomically replaces only the protected hash file, and restarts only the
dashboard. Plaintext is not written to disk or command history.

## Pages

- `/` — system health and task overview;
- `/tasks` and `/tasks/{id}` — owner-scoped tasks and safe details;
- `/agents` and `/agents/{id}` — manifests and approval-gated management;
- `/skills` and `/skills/{id}` — reviewed manifests and lifecycle management;
- `/api-keys` — scoped key requests, rotation, disable, and delete;
- `/webhooks` — HTTPS event endpoints and failure state;
- `/metrics` — safe owner-scoped usage counters;
- `/integrations` — GitHub and Content capability status;
- `/approvals` — existing approval records and decisions;
- `/audit` — sanitized audit records.

Screenshots are intentionally deferred until the UI is connected through a
trusted local tunnel.

The host timer `nexora-dashboard-health.timer` refreshes a sanitized status
snapshot once per minute. It records only service availability and a timestamp;
the dashboard container never receives the Docker socket.
