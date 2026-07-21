# Installation and operations

## One-command local deployment

Run `sudo ./install.sh` on Linux with Docker Engine, Compose v2, Python 3, OpenSSL,
and curl. The script is fail-closed: it validates prerequisites and Compose,
generates protected secrets, builds images, starts the release project, and
waits for all health checks.

Root is used only to assign generated host secret files to fixed UID/GID 10001;
the long-running containers remain non-root and the mounts are read-only.

Optional non-secret settings may be exported before installation:

```bash
export NEXORA_DASHBOARD_PORT=18880
export NEXORA_API_PORT=18881
export COMPOSE_PROJECT_NAME=nexora-release
./install.sh
```

Both ports bind only to `127.0.0.1`. Use an SSH tunnel for remote access.

## Volumes

`nexora-state` contains task state and SQLite; `nexora-status` contains bounded
health status. Back up both before an upgrade. Secret files under `.secrets/`
must be backed up only using approved encrypted storage.

## Health and logs

```bash
docker compose -f docker-compose.release.yml ps
docker compose -f docker-compose.release.yml logs --tail=100
curl -k https://127.0.0.1:18880/healthz
curl -k https://127.0.0.1:18881/healthz
```

## Rollback

Validate a tag before action:

```bash
scripts/rollback-release.sh --check v1.8.0
```

Execution creates a Git bundle and refuses a dirty worktree. Run rollback only
against a public release deployment, not an unrelated production installation.
