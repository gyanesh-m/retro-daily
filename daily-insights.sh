#!/bin/bash
# daily-insights.sh — Global SessionStart hook.
# Always renders the dashboard from the cached store immediately (non-blocking).
# When the store is stale for today, spawns a detached background worker to
# regenerate (embedding classification is expensive) — fresh numbers appear in
# the next session, mirroring the scout worker pattern.
set -e
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_paths.sh"

LAST_RUN_FILE="$RETRO_DAILY_DATA/last-run-date.txt"
STORE_FILE="$RETRO_DAILY_DATA/metrics-store.json"
VENV_PYTHON="$RETRO_DAILY_DATA/.venv/bin/python3"
RUNNER="$RETRO_DAILY_HOME/daily-insights-runner.sh"
LOG="$RETRO_DAILY_DATA/daily-insights.log"
TODAY=$(date +%Y-%m-%d)

PY="python3"
[ -x "$VENV_PYTHON" ] && PY="$VENV_PYTHON"

# 1. Render the cached dashboard first — fast, never blocks. On the very first
#    run there is no store yet, so show a short building banner instead.
if [ -f "$STORE_FILE" ]; then
    RETRO_DAILY_HOME="$RETRO_DAILY_HOME" RETRO_DAILY_DATA="$RETRO_DAILY_DATA" \
    "$PY" - <<'PYEOF' 2>/dev/null || true
import sys, os
from pathlib import Path
code_dir = Path(os.environ["RETRO_DAILY_HOME"])
sys.path.insert(0, str(code_dir))
import importlib.util
spec = importlib.util.spec_from_file_location("gm", code_dir / "generate-metrics.py")
gm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gm)
store = gm.load_store()
from datetime import date, timedelta
yesterday = (date.today() - timedelta(days=1)).isoformat()
gm.print_insights(store, yesterday)
PYEOF
else
    echo "[insights] building your first dashboard — ready in the next session"
fi

# 2. If the store is stale for today, regenerate in the background.
if [ ! -f "$LAST_RUN_FILE" ] || [ "$(cat "$LAST_RUN_FILE" 2>/dev/null)" != "$TODAY" ]; then
    # Gate: don't spawn if a worker is already live (last-run-date.txt isn't
    # written until the worker finishes, so rapid sessions could otherwise
    # each spawn during a long regen).
    if pgrep -f "daily-insights-runner.sh" >/dev/null 2>&1; then
        echo "[insights] metrics already refreshing in background — new numbers next session"
        exit 0
    fi
    # Fallback: if the runner is missing entirely, regenerate inline so the
    # dashboard still updates (degraded — this one session blocks).
    if [ ! -f "$RUNNER" ]; then
        "$PY" "$RETRO_DAILY_HOME/generate-metrics.py" >/dev/null 2>&1 || true
        exit 0
    fi
    # Spawn fully-detached worker. Truncate the log per run so it can't grow
    # unbounded. The runner traps SIGHUP to survive the session closing.
    : > "$LOG"
    nohup bash "$RUNNER" </dev/null >> "$LOG" 2>&1 &
    disown
    SHORT_LOG="${LOG/#$HOME/\~}"
    echo "[insights] refreshing metrics in background — updated numbers appear next session · log: $SHORT_LOG"
fi
