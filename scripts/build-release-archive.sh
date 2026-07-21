#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
[ -z "$(git status --porcelain)" ] || { echo 'Release archive requires a clean worktree.' >&2; exit 1; }
[ "$(cat VERSION)" = 2.0.0 ] || { echo 'Unexpected VERSION.' >&2; exit 1; }
mkdir -p release-artifacts
archive="release-artifacts/nexora-2.0.0.tar.gz"
git archive --format=tar.gz --prefix=nexora-2.0.0/ --output="$archive.tmp" HEAD
mv "$archive.tmp" "$archive"
sha256sum "$archive" > "$archive.sha256"
if tar -tzf "$archive" | grep -Eq '(^|/)\.env$|(^|/)\.secrets/|runtime/state/.*\.(json|db|sqlite)'; then
  echo 'Sensitive release path found.' >&2
  exit 1
fi
sha256sum -c "$archive.sha256"
echo "release_archive=PASS path=$archive"
