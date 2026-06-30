#!/usr/bin/env bash
# Cron example: 0 3 * * 0 cd /path/to/vrcx2trakt && scripts/auto_sync.sh
# Run `vrcx2trakt setup` and `vrcx2trakt login` once before scheduling.

set -euo pipefail

if command -v vrcx2trakt >/dev/null 2>&1; then
  cmd=(vrcx2trakt sync)
elif command -v python3 >/dev/null 2>&1; then
  cmd=(python3 -m vrcx2trakt sync)
elif command -v python >/dev/null 2>&1; then
  cmd=(python -m vrcx2trakt sync)
else
  echo "Error: vrcx2trakt is not on PATH and no Python executable was found." >&2
  exit 127
fi

state_dir="${VRCX2TRAKT_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/vrcx2trakt}"
log_dir="$state_dir/logs"
mkdir -p "$log_dir"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
log_file="$log_dir/sync-$timestamp.log"

{
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting vrcx2trakt sync"
  echo "Command: ${cmd[*]}"
  echo "If this fails with an authorisation error, run: vrcx2trakt setup && vrcx2trakt login"
  echo
} | tee "$log_file"

if "${cmd[@]}" >>"$log_file" 2>&1; then
  echo "vrcx2trakt sync completed. Log: $log_file"
else
  status=$?
  echo "vrcx2trakt sync failed with exit code $status. Log: $log_file" >&2
  tail -n 40 "$log_file" >&2 || true
  exit "$status"
fi
