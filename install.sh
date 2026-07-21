#!/usr/bin/env bash
set -euo pipefail

project=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project"
umask 077

[ "$(id -u)" -eq 0 ] || { echo "Run install.sh as root; containers still run as non-root UID 10001." >&2; exit 1; }

for command in docker python3 openssl curl; do
  command -v "$command" >/dev/null 2>&1 || { echo "Missing dependency: $command" >&2; exit 1; }
done
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required." >&2; exit 1; }
[ -r VERSION ] && [ "$(tr -d '\r\n' < VERSION)" = "2.0.0" ] || { echo "Unsupported release version." >&2; exit 1; }

if [ ! -e .env ]; then
  cp .env.example .env
  chmod 600 .env
fi
[ ! -L .env ] && [ "$(stat -c '%a' .env)" = "600" ] || { echo ".env must be a regular mode-600 file." >&2; exit 1; }

mkdir -p .secrets
chmod 700 .secrets
python3 scripts/generate-release-secrets.py

if [ ! -s .secrets/dashboard_tls_cert ] || [ ! -s .secrets/dashboard_tls_key ]; then
  temporary_key=.secrets/.dashboard_tls_key.$$
  temporary_cert=.secrets/.dashboard_tls_cert.$$
  trap 'rm -f "$temporary_key" "$temporary_cert"' EXIT
  openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 \
    -subj '/CN=localhost' -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1' \
    -keyout "$temporary_key" -out "$temporary_cert" >/dev/null 2>&1
  chmod 600 "$temporary_key" "$temporary_cert"
  mv "$temporary_key" .secrets/dashboard_tls_key
  mv "$temporary_cert" .secrets/dashboard_tls_cert
  trap - EXIT
fi
chmod 600 .secrets/*
chown -R 10001:10001 .secrets
chmod 700 .secrets
chmod 600 .secrets/*

compose=(docker compose -f docker-compose.release.yml)
"${compose[@]}" config --quiet
"${compose[@]}" build
"${compose[@]}" up -d

deadline=$((SECONDS + 180))
services=(database nexora-runtime nexora-dashboard nexora-api)
for service in "${services[@]}"; do
  while :; do
    container=$("${compose[@]}" ps -q "$service")
    health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container" 2>/dev/null || true)
    [ "$health" = healthy ] && break
    [ "$health" = unhealthy ] && { echo "$service is unhealthy" >&2; exit 1; }
    [ "$SECONDS" -lt "$deadline" ] || { echo "Timed out waiting for $service" >&2; exit 1; }
    sleep 2
  done
done

dashboard_port=${NEXORA_DASHBOARD_PORT:-18880}
api_port=${NEXORA_API_PORT:-18881}
curl --fail --silent --show-error --insecure "https://127.0.0.1:${dashboard_port}/healthz" >/dev/null
curl --fail --silent --show-error --insecure "https://127.0.0.1:${api_port}/healthz" >/dev/null
printf 'Nexora 2.0 is healthy.\nDashboard: https://127.0.0.1:%s\nAPI: https://127.0.0.1:%s\n' "$dashboard_port" "$api_port"
