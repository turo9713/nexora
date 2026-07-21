#!/usr/bin/env bash
set -euo pipefail

project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo 'secret_scan=FAIL reason=not_a_git_repository'; exit 1; }

bad_path='(^|/)(\.env($|\.)|\.secrets/|secrets?/|runtime/state/|logs/.*\.(log|jsonl)$|.*\.(sqlite3?|db|pem|p12|pfx|key)$)'
if git ls-files | grep -E "$bad_path" | grep -vE '(^|/)\.env\.example$' >/dev/null; then
  echo 'secret_scan=FAIL reason=sensitive_path_tracked'
  exit 1
fi
if git log --all --name-only --format= | sed '/^$/d' | sort -u | grep -E "$bad_path" | grep -vE '(^|/)\.env\.example$' >/dev/null; then
  echo 'secret_scan=FAIL reason=sensitive_path_in_history'
  exit 1
fi

pattern="([0-9]{8,10}:[A-Za-z0-9_-]{20,}|sk-(proj-)?[A-Za-z0-9_-]{20,}|nx_live_[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|Authorization:[[:space:]]*(Bearer|Basic)[[:space:]]+[A-Za-z0-9._~+/=-]{12,}|(password|passwd|api[_-]?key|token)[[:space:]]*[:=][[:space:]]*[\"'][A-Za-z0-9_./+=-]{20,}[\"'])"
paths=(-- . ':(exclude)integrations/telegram_runtime/tests/**' ':(exclude)dashboard/tests/**' ':(exclude)tests/**')
if git grep -I -E -q "$pattern" "${paths[@]}"; then
  echo 'secret_scan=FAIL reason=credential_pattern_in_worktree'
  exit 1
fi
for revision in $(git rev-list --all); do
  if git grep -I -E -q "$pattern" "$revision" "${paths[@]}"; then
    echo 'secret_scan=FAIL reason=credential_pattern_in_history'
    exit 1
  fi
done

scan_known_value() {
  local value=$1
  [ -n "$value" ] || return 0
  local revision
  for revision in $(git rev-list --all); do
    if git grep -F -q -e "$value" "$revision" -- .; then
      echo 'secret_scan=FAIL reason=known_production_value_in_history'
      exit 1
    fi
  done
}

known_secret_dir=${NEXORA_KNOWN_SECRET_DIR:-}
if [ -n "$known_secret_dir" ] && [ -d "$known_secret_dir" ]; then
  for secret_file in "$known_secret_dir"/*; do
    [ -s "$secret_file" ] || continue
    scan_known_value "$(tr -d '\r\n' < "$secret_file")"
  done
fi
owner_file=${NEXORA_OWNER_ENV_FILE:-}
if [ -n "$owner_file" ] && [ -r "$owner_file" ]; then
  scan_known_value "$(sed -n 's/^NEXORA_TELEGRAM_OWNER_ID=//p' "$owner_file" | tr -d '\r\n')"
fi

echo 'secret_scan=PASS history=PASS known_production_values=PASS'
