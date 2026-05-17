#!/bin/bash
# startup.sh — Single SessionStart hook that runs all startup scripts sequentially.
# Each step runs independently (one failure does not skip the rest). Per-step
# output + timing mirrored to /tmp/claude-startup.log for debugging what
# Claude Code's hook pipeline actually receives.
# NOTE: no `set -e` — we want every step to execute even if an earlier one errors.
#
# ─── How SessionStart hook output reaches the user vs. the LLM ───────────────
#
# Per Claude Code's hook spec (https://code.claude.com/docs/en/hooks):
#
#     SessionStart hook fires
#               │
#       ┌───────┴────────┐
#       ▼                ▼
#   Plain stdout    JSON output
#       │                │
#       ▼        ┌───────┴───────┐
#   Claude's     ▼               ▼
#   context  systemMessage   additionalContext
#   ONLY     (VISIBLE to     (Claude's context
#  (hidden    user in        only — invisible)
#   from      terminal)
#   user)
#
# In Claude Code v2.1.x's full-screen TUI, plain stdout from a plugin's
# SessionStart hook is captured into the LLM's `additionalContext` and is NOT
# rendered visibly. To make the dashboard appear at the top of the user's
# session, we MUST emit a JSON document with `systemMessage` set to the
# rendered output. We also include `hookSpecificOutput.additionalContext` so
# the model still gets the same view of the dashboard.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_paths.sh"

DEBUG_LOG="/tmp/claude-startup.log"
{
  echo "===== startup.sh invoked at $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
  echo "TERM=$TERM  PWD=$PWD  USER=${USER:-?}"
  echo "CLAUDE_CODE_SESSION=${CLAUDE_CODE_SESSION:-unset}"
  echo "PATH=$PATH"
} >> "$DEBUG_LOG" 2>&1

# Accumulate every step's stdout into a single buffer. At the end we emit
# the entire concatenated output as one JSON document so it lands in
# systemMessage (user-visible) AND additionalContext (LLM-visible).
ACCUMULATED=""

run_step() {
  local name="$1"; shift
  local t0=$(date +%s)
  local out rc
  out=$("$@" 2>&1); rc=$?
  local t1=$(date +%s)
  {
    echo "[$name] exit=$rc bytes=${#out} seconds=$((t1-t0))"
    echo "----- begin [$name] stdout -----"
    printf '%s\n' "$out"
    echo "----- end [$name] stdout -----"
  } >> "$DEBUG_LOG"
  # Append to the buffer that will end up in systemMessage + additionalContext.
  ACCUMULATED="${ACCUMULATED}${out}"$'\n'
}

# Order matters: dashboard first (scrolls to top of terminal), scout findings
# LAST so they stay visible near the prompt when the session opens. Earlier
# reverse order buried scout above the viewport.
run_step "daily-insights" bash "$RETRO_DAILY_HOME/daily-insights.sh" || true
run_step "scout"          bash "$RETRO_DAILY_HOME/scout.sh"          || true
run_step "tag-sessions"   bash "$RETRO_DAILY_HOME/tag-sessions.sh"   || true
run_step "scout-review"   bash "$RETRO_DAILY_HOME/scout-review.sh"   || true

# Emit the SessionStart hook JSON response. Reads ACCUMULATED from stdin so we
# don't have to worry about shell quoting of multi-line ANSI-colored content.
printf '%s' "$ACCUMULATED" | python3 -c '
import json, sys
content = sys.stdin.read().rstrip("\n")
print(json.dumps({
    "systemMessage": content,
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": content,
    },
}))
' 2>>"$DEBUG_LOG"

echo "===== startup.sh finished at $(date -u +%Y-%m-%dT%H:%M:%SZ) =====" >> "$DEBUG_LOG"
