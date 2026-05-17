#!/bin/bash
# tag-sessions.sh — SessionStart gate. Once per week (or when forced), spawns
# the tag-sessions-runner background worker that asks Claude to label each
# recent session with a topic and interaction type.
#
# Mirrors scout.sh's gate-and-spawn pattern (lock files, nohup, log).
set -e
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_paths.sh"

HISTORY_FILE="$RETRO_DAILY_DATA/analysis-history.json"
RUNNER="$RETRO_DAILY_HOME/tag-sessions-runner.sh"
LOG="$RETRO_DAILY_DATA/tag-sessions.log"

TAG_STALE_DAYS=${TAG_STALE_DAYS:-7}

# Compute days since last tagging run.
DAYS_SINCE=$(python3 -c "
import json
from datetime import date
try:
    h = json.load(open('$HISTORY_FILE'))
    last = h.get('last_session_tagging')
    if not last:
        print(9999)
    else:
        print((date.today() - date.fromisoformat(last)).days)
except Exception:
    print(9999)
" 2>/dev/null || echo "9999")

# Allow forcing via env var: TAG_FORCE=1 bash tag-sessions.sh
if [ "${TAG_FORCE:-0}" != "1" ] && [ "$DAYS_SINCE" -lt "$TAG_STALE_DAYS" ]; then
  exit 0
fi

# Don't spawn if a runner is already live.
if pgrep -f "tag-sessions-runner.sh" >/dev/null 2>&1; then
  echo "[tag-sessions] skipped — background worker already running"
  exit 0
fi

if [ ! -x "$RUNNER" ]; then
  echo "[tag-sessions] runner missing or not executable: $RUNNER"
  exit 0
fi

# Spawn fully-detached background worker. Same SIGHUP-safe pattern as scout.
nohup bash "$RUNNER" </dev/null >> "$LOG" 2>&1 &
disown

SHORT_LOG="${LOG/#$HOME/\~}"
echo "[tag-sessions] queued (last run $DAYS_SINCE days ago), results next session · log: $SHORT_LOG"
