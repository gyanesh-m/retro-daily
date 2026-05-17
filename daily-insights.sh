#!/bin/bash
# daily-insights.sh — Global SessionStart hook.
# Regenerates metrics once per day (expensive: embedding classification).
# Always renders the dashboard from the cached store on every session.
set -e
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_paths.sh"

LAST_RUN_FILE="$RETRO_DAILY_DATA/last-run-date.txt"
VENV_PYTHON="$RETRO_DAILY_DATA/.venv/bin/python3"
TODAY=$(date +%Y-%m-%d)

PY="python3"
[ -x "$VENV_PYTHON" ] && PY="$VENV_PYTHON"

# Full regenerate (writes metrics-store.json + prints dashboard) — once per day.
if [ ! -f "$LAST_RUN_FILE" ] || [ "$(cat "$LAST_RUN_FILE" 2>/dev/null)" != "$TODAY" ]; then
    "$PY" "$RETRO_DAILY_HOME/generate-metrics.py" 2>/dev/null || true
    exit 0
fi

# Already regenerated today — just reprint the dashboard from the cached store.
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
