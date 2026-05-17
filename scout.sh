#!/bin/bash
# scout.sh — SessionStart hook. Spawns a real background scout worker when weak
# metrics have changed since the last scouted set.
set -e
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_paths.sh"

QUERIES_FILE="$RETRO_DAILY_DATA/scout-queries.json"
HISTORY_FILE="$RETRO_DAILY_DATA/analysis-history.json"
RUNNER="$RETRO_DAILY_HOME/scout-runner.sh"
LOG="$RETRO_DAILY_DATA/scout.log"

[ -f "$QUERIES_FILE" ] || exit 0

CURRENT_METRICS=$(python3 -c "
import json
d = json.load(open('$QUERIES_FILE'))
print(','.join(sorted(d.get('weak_metrics', []))))
" 2>/dev/null || echo "")

[ -z "$CURRENT_METRICS" ] && exit 0

LAST_SCOUT_METRICS=$(python3 -c "
import json
h = json.load(open('$HISTORY_FILE'))
print(','.join(sorted(h.get('last_scout_metrics', []))))
" 2>/dev/null || echo "")

# Compute days since last scout. Re-run weekly even if metrics unchanged so the
# findings stay fresh (web docs, trending repos evolve).
DAYS_SINCE=$(python3 -c "
import json
from datetime import date
try:
    h = json.load(open('$HISTORY_FILE'))
    last = h.get('last_scout')
    if not last:
        print(9999)
    else:
        print((date.today() - date.fromisoformat(last)).days)
except Exception:
    print(9999)
" 2>/dev/null || echo "9999")

SCOUT_STALE_DAYS=${SCOUT_STALE_DAYS:-7}

# Gate 1: skip only if metrics unchanged AND scout is fresh (<$SCOUT_STALE_DAYS days old)
if [ "$CURRENT_METRICS" = "$LAST_SCOUT_METRICS" ] && [ "$DAYS_SINCE" -lt "$SCOUT_STALE_DAYS" ]; then
  exit 0
fi

# Gate 2: don't spawn if a runner is already live
if pgrep -f "scout-runner.sh" >/dev/null 2>&1; then
  echo "[scout] skipped — background worker already running"
  exit 0
fi

# Gate 3: runner must exist and be executable
if [ ! -x "$RUNNER" ]; then
  echo "[scout] runner missing or not executable: $RUNNER"
  exit 0
fi

# Spawn fully-detached background worker. macOS lacks `setsid`; the runner itself
# traps SIGHUP to survive the parent Claude Code session closing (previous attempts
# died with exit 129 when sessions ended).
nohup bash "$RUNNER" </dev/null >> "$LOG" 2>&1 &
disown

# Print queries one-per-line + shortened log path so nothing wraps in narrow
# viewports. Joining all queries on a single ` · `-separated line and printing
# the absolute /Users/... log path both blew past 80 chars and wrapped ugly.
SHORT_LOG="${LOG/#$HOME/\~}"
python3 - "$QUERIES_FILE" "$SHORT_LOG" <<'PY_EOF'
import json, sys
queries_file, short_log = sys.argv[1], sys.argv[2]
try:
    queries = json.load(open(queries_file)).get('queries', [])
except Exception:
    queries = []
print(f"[scout] queued — {len(queries)} queries, results in next session · log: {short_log}")
for q in queries:
    print(f"  · {q}")
PY_EOF
