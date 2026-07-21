#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
mode=${1:-}
target=${2:-v1.8.0}
case "$mode" in --check|--execute) ;; *) echo "Usage: $0 --check|--execute [tag]" >&2; exit 2;; esac
git rev-parse --verify "refs/tags/$target" >/dev/null
[ -z "$(git status --porcelain)" ] || { echo 'Rollback refused: worktree is dirty.' >&2; exit 1; }
current=$(git rev-parse HEAD)
git merge-base --is-ancestor "$target" "$current" || { echo 'Rollback tag is unrelated.' >&2; exit 1; }
if [ "$mode" = --check ]; then
  echo "rollback_check=PASS target=$target"
  exit 0
fi
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="$root/backups-release/$timestamp"
mkdir -p "$backup"
chmod 700 "$root/backups-release" "$backup"
git bundle create "$backup/pre-rollback.bundle" --all
sha256sum "$backup/pre-rollback.bundle" > "$backup/SHA256SUMS"
chmod 600 "$backup"/*
git switch --detach "$target"
echo "rollback=PASS target=$target backup=$backup compose_action=none"
