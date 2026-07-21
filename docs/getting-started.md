# Getting started

## Welcome to Nexora

1. Connect Telegram using a protected secret file.
2. Select a validated workflow template in Dashboard.
3. Run the first sandboxed task.
4. Review the result and any requested approval before an external action.

For a no-side-effect tour, open `/playground`. It exposes examples only and never publishes, writes externally, or reads secrets.

## Requirements

- Linux host with Docker Engine and Docker Compose v2.
- Python 3, OpenSSL, and curl for the installer.
- At least 2 CPU cores, 4 GB RAM, and 10 GB free disk for a local evaluation.

## Install

```bash
git clone https://github.com/turo9713/nexora.git
cd nexora
cp .env.example .env
sudo ./install.sh
```

The installer generates protected local secrets and starts `database`,
`nexora-runtime`, `nexora-dashboard`, and `nexora-api`. Dashboard and API bind
to host localhost by default.

## Verify

```bash
docker compose -f docker-compose.release.yml ps
curl --fail --insecure https://127.0.0.1:18880/healthz
curl --fail --insecure https://127.0.0.1:18881/healthz
```

For remote administration, use an SSH tunnel. Do not expose OpenClaw Gateway or
the Dashboard directly to the public Internet.

## Demo

```bash
python3 examples/demo_content_workflow.py
```

The demo is offline and follows Research, Content, QA, Approval, and Result. It
does not publish content, send external messages, or change production.
