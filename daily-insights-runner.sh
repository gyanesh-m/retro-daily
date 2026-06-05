#!/bin/bash
# daily-insights-runner.sh — Detached background worker that regenerates the
# metrics store. Invoked by daily-insights.sh via nohup.
#
# Pure local Python: it only runs generate-metrics.py (no `claude -p`, no
# network, no sandbox needed). generate-metrics.py saves metrics-store.json and
# writes last-run-date.txt itself, so this worker does no extra bookkeeping.
set -u

# Survive parent Claude Code session closing. macOS lacks setsid, so trap SIGHUP.
trap '' HUP

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_paths.sh"

LOG="$RETRO_DAILY_DATA/daily-insights.log"
LOCK="$RETRO_DAILY_DATA/.daily-insights.lock"
VENV_PYTHON="$RETRO_DAILY_DATA/.venv/bin/python3"

PY="python3"
[ -x "$VENV_PYTHON" ] && PY="$VENV_PYTHON"

log() { echo "[$(date +%H:%M:%S)] $*" >> "$LOG"; }

# Coarse lock: skip if another runner is already live.
if [ -f "$LOCK" ]; then
  pid=$(cat "$LOCK" 2>/dev/null || echo "")
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    log "daily-insights-runner: another instance (pid=$pid) running, aborting"
    exit 0
  fi
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

log "daily-insights-runner: starting regen (PY=$PY)"
# generate-metrics.py scans only new dates + yesterday, saves the store, and
# writes last-run-date.txt. Its trailing dashboard print lands in the log.
if "$PY" "$RETRO_DAILY_HOME/generate-metrics.py" >> "$LOG" 2>&1; then
  log "daily-insights-runner: regen complete"
else
  rc=$?
  log "daily-insights-runner: regen FAILED (exit $rc)"
  exit 1
fi
