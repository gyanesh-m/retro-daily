#!/bin/bash
# scout-review.sh — SessionStart hook. Renders unreviewed scout findings in the
# editorial dashboard style, then asks Claude to discuss them with the user.
set -e
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_paths.sh"

RESULTS_FILE="$RETRO_DAILY_DATA/scout-results.json"

[ -f "$RESULTS_FILE" ] || exit 0

# Always render findings at session start (like FOCUS AREAS). The `reviewed` flag
# is kept for historical compatibility but no longer gates display.

# Render findings using the same ANSI / typography vocabulary as generate-metrics.py
RETRO_DAILY_DATA="$RETRO_DAILY_DATA" python3 <<'PYEOF'
import json, os, re
from pathlib import Path

RESULTS_FILE = Path(os.environ["RETRO_DAILY_DATA"]) / "scout-results.json"
data = json.load(open(RESULTS_FILE))

def _c(code): return f"\033[{code}m"
RESET = _c(0); BOLD = _c(1); DIM = _c(2)
CYAN = _c(36); BRIGHT_CYAN = _c(96); BRIGHT_WHITE = _c(97)
BRIGHT_YELLOW = _c(93); BRIGHT_GREEN = _c(92)
RULE = 68

title = "SCOUT FINDINGS"
spaced = ' '.join(title)
print(f"{BRIGHT_CYAN}{BOLD}{spaced}{RESET}")
print(f"{BRIGHT_CYAN}{'━' * RULE}{RESET}")
n_recs = len(data.get('recommendations', []))
print(f"{DIM}{n_recs} queries · {data.get('date','?')} · full detail: {RESULTS_FILE}{RESET}")
print()

# Ultra-compact: top pick per query, one line each. Surfaces the single most
# actionable item across all findings — full details remain in the JSON file.
def truncate(s, n):
    return s if len(s) <= n else s[:n-1] + "…"

# Pick the first finding (ranked by Claude) from each query, preferring ones with actionable text.
picks = []
for rec in data.get("recommendations", []):
    q = rec.get("query", "")
    findings = rec.get("findings", [])
    # Prefer non-trending finding as primary (usually the doc/tip), but include one trending if present
    primary = next((f for f in findings if not f.get("title","").startswith("[trending]")), findings[0] if findings else None)
    trending = next((f for f in findings if f.get("title","").startswith("[trending]")), None)
    picks.append((q, primary, trending))

for q, primary, trending in picks:
    print(f"  {BRIGHT_YELLOW}●{RESET} {BOLD}{truncate(q, 50)}{RESET}")
    if primary:
        a = truncate(primary.get("actionable", primary.get("summary", "")), 120)
        print(f"      {BRIGHT_GREEN}→{RESET} {a}")
    if trending:
        # Print the bare GitHub URL as plain text so the terminal auto-detects
        # and makes it cmd-clickable — no OSC 8 escapes (those render as garbage
        # in terminals/TUIs that don't support them and break the layout).
        url = trending.get("url", "")
        label = url or truncate(trending.get("title", "")[11:], 38)
        a = truncate(trending.get("actionable", trending.get("summary", "")), 60)
        print(f"      {DIM}★ {BRIGHT_WHITE}{label}{RESET}{DIM} · {a}{RESET}")

print()
print(f"{DIM}{'─' * RULE}{RESET}")
# Trailing blank lines: Sage's SessionStart hook runs after this one and its
# node output / status line can visually overwrite the last rendered entry.
# Pad a few lines so the last recommendation stays visible above Sage's output.
print()
print()
print()
PYEOF

