# Release containers

`docker-compose.release.yml` builds one immutable image and runs four isolated
roles: database migration/health, runtime registry/health, Dashboard, and API.
Only Dashboard and API publish host ports, both on `127.0.0.1` by default.

No service uses privileged mode, host networking, root, extra capabilities, or
the Docker socket. Writable named volumes are limited to runtime state/status.
Protected files under `.secrets/` are mounted read-only by Compose.

OpenClaw Gateway and Telegram production polling are intentionally not part of
this public deployment.
