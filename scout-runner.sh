#!/bin/bash
# scout-runner.sh — Headless background worker that runs scout queries via `claude -p`
# and writes results to scout-results.json.
#
# Invoked by scout.sh via nohup. Writes progress to scout.log.
set -u

# Survive parent Claude Code session closing. macOS lacks setsid, so trap SIGHUP.
trap '' HUP

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_paths.sh"

QUERIES_FILE="$CLAUDE_DAILY_DATA/scout-queries.json"
RESULTS_FILE="$CLAUDE_DAILY_DATA/scout-results.json"
HISTORY_FILE="$CLAUDE_DAILY_DATA/analysis-history.json"
LOG="$CLAUDE_DAILY_DATA/scout.log"
LOCK="$CLAUDE_DAILY_DATA/.scout.lock"

log() { echo "[$(date +%H:%M:%S)] $*" >> "$LOG"; }

# Acquire lock (coarse): skip if another runner is live
if [ -f "$LOCK" ]; then
  pid=$(cat "$LOCK" 2>/dev/null || echo "")
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    log "scout-runner: another instance (pid=$pid) running, aborting"
    exit 0
  fi
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

if [ ! -f "$QUERIES_FILE" ]; then
  log "no scout-queries.json, nothing to do"
  exit 0
fi

TODAY=$(date +%Y-%m-%d)
QUERIES=$(python3 -c "import json; d=json.load(open('$QUERIES_FILE')); print('\n'.join(d.get('queries', [])))")
WEAK=$(python3 -c "import json; d=json.load(open('$QUERIES_FILE')); print(','.join(d.get('weak_metrics', [])))")

if [ -z "$QUERIES" ]; then
  log "no queries in scout-queries.json"
  exit 0
fi

log "scout-runner: starting for metrics=[$WEAK]"
log "queries:"
while IFS= read -r q; do log "  - $q"; done <<< "$QUERIES"

# Have Claude write to /tmp (unrestricted), then we'll mv into $CLAUDE_DAILY_DATA.
# ~/.claude/ is treated as a sensitive path and triggers permission prompts even with
# --allowedTools — writing to /tmp sidesteps that cleanly.
TMP_RESULTS="/tmp/claude-scout-results-$$.json"

# Build the prompt. Claude will WebSearch each query, then Write scout-results.json.
PROMPT=$(cat <<PROMPT_EOF
You are a scout worker. You have two jobs:

JOB 1 — For each of the following queries, use WebSearch to find 2-3 recent, actionable tips.
Prefer sources from docs.anthropic.com, github.com, claude.com, reddit.com.

Queries:
$QUERIES

JOB 2 — Creativity / trending. For each query, also do ONE additional WebSearch scoped to GitHub
to surface a fresh or trending repo that addresses the underlying problem. Use queries like:
  "site:github.com <topic> 2026"
  "github trending <topic>"
  "github.com/trending <topic>"
Prefer repos with recent activity (past 3 months), >100 stars or clearly novel. Return each as
an additional finding inside the same query block, with "title" prefixed "[trending] " and "url"
pointing to the repo. This gives the user creative angles, not just docs.

Then use the Write tool to create the file $TMP_RESULTS with this exact JSON schema:

{
  "date": "$TODAY",
  "reviewed": false,
  "weak_metrics": [$(python3 -c "import json; d=json.load(open('$QUERIES_FILE')); print(', '.join(repr(m) for m in d.get('weak_metrics', [])))")],
  "recommendations": [
    {
      "query": "<the query>",
      "findings": [
        {
          "title": "<short title, prefix '[trending] ' for github finds>",
          "summary": "<one-sentence summary>",
          "url": "<source url>",
          "actionable": "<concrete thing the user can do>"
        }
      ]
    }
  ]
}

Rules:
- 2-3 doc/tip findings + 1 trending-repo finding per query. Max ~3 lines per finding.
- "actionable" must be concrete — something the user can do in the next session.
- Do not print additional commentary after writing.
PROMPT_EOF
)

# Run claude headlessly with narrow tool scope. --allowedTools pre-approves WebSearch + Write
# (no permission prompts), so the worker does not need --allow-dangerously-skip-permissions.
# Do NOT use --bare: it disables OAuth/keychain auth and requires ANTHROPIC_API_KEY.
export CLAUDE_CODE_DISABLE_SESSION_START_HOOK=1
log "invoking claude -p (WebSearch+Write only)"
CLAUDE_OUT=$(claude -p \
  --allowedTools "WebSearch Write" \
  --append-system-prompt "You are an unattended background scout worker. Only use WebSearch and Write. Write ONLY to $TMP_RESULTS. Be decisive; skip clarifying questions." \
  "$PROMPT" 2>&1) || {
    log "claude -p failed (exit $?). output follows:"
    echo "$CLAUDE_OUT" | tail -40 >> "$LOG"
    exit 1
  }

log "claude -p completed. output (last 60 lines):"
echo "$CLAUDE_OUT" | tail -60 >> "$LOG"
log "---end claude output---"

if [ ! -f "$TMP_RESULTS" ]; then
  log "WARNING: temp results file was not written ($TMP_RESULTS)"
  exit 1
fi

# Validate JSON before moving into the sensitive directory
if ! python3 -c "import json; json.load(open('$TMP_RESULTS'))" 2>/dev/null; then
  log "WARNING: $TMP_RESULTS is not valid JSON"
  cp "$TMP_RESULTS" "$LOG.bad-results.json" 2>/dev/null
  rm -f "$TMP_RESULTS"
  exit 1
fi

# Archive the previous results (if any) before overwriting, so search/history is preserved.
ARCHIVE_DIR="$CLAUDE_DAILY_DATA/scout-archive"
mkdir -p "$ARCHIVE_DIR"
if [ -f "$RESULTS_FILE" ]; then
  PREV_DATE=$(python3 -c "import json; d=json.load(open('$RESULTS_FILE')); print(d.get('date','unknown'))" 2>/dev/null || echo "unknown")
  # Suffix with a timestamp so same-day re-runs don't collide
  ARCHIVE_NAME="$ARCHIVE_DIR/$PREV_DATE-$(date +%H%M%S).json"
  cp "$RESULTS_FILE" "$ARCHIVE_NAME" && log "archived previous results to $ARCHIVE_NAME"
fi

mv "$TMP_RESULTS" "$RESULTS_FILE"
log "moved results into $RESULTS_FILE"

# Update analysis-history.json
python3 <<PYEOF
import json
from pathlib import Path
h_path = Path("$HISTORY_FILE")
if h_path.exists():
    h = json.load(open(h_path))
else:
    h = {"last_analysis": None, "last_scout": None, "weak_metrics_history": [], "scouted_repos": [], "recommendations_given": []}
h["last_scout"] = "$TODAY"
h["last_scout_metrics"] = sorted("$WEAK".split(",")) if "$WEAK" else []
json.dump(h, open(h_path, "w"), indent=2)
PYEOF

log "analysis-history.json updated (last_scout=$TODAY)"
log "scout-runner: done"
