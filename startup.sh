#!/bin/bash
# startup.sh — Single SessionStart hook that runs all startup scripts sequentially.
# Each step runs independently (one failure does not skip the rest). Per-step
# output + timing mirrored to /tmp/claude-startup.log for debugging what
# Claude Code's hook pipeline actually receives.
# NOTE: no `set -e` — we want every step to execute even if an earlier one errors.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_paths.sh"

DEBUG_LOG="/tmp/claude-startup.log"
{
  echo "===== startup.sh invoked at $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
  echo "TERM=$TERM  PWD=$PWD  USER=${USER:-?}"
  echo "CLAUDE_CODE_SESSION=${CLAUDE_CODE_SESSION:-unset}"
  echo "PATH=$PATH"
} >> "$DEBUG_LOG" 2>&1

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
  # Emit to real stdout so Claude Code's hook feeds it into the LLM context.
  printf '%s\n' "$out"
  # ALSO emit to /dev/tty so the user actually sees it in their terminal even
  # when Claude Code's CLI swallows the hook's stdout visually.
  if [ -w /dev/tty ]; then
    printf '%s\n' "$out" > /dev/tty 2>/dev/null || true
  fi
}

# Order matters: dashboard first (scrolls to top of terminal), scout findings
# LAST so they stay visible near the prompt when the session opens. Earlier
# reverse order buried scout above the viewport.
run_step "daily-insights" bash "$CLAUDE_DAILY_HOME/daily-insights.sh" || true
run_step "scout"          bash "$CLAUDE_DAILY_HOME/scout.sh"          || true
run_step "scout-review"   bash "$CLAUDE_DAILY_HOME/scout-review.sh"   || true

echo "===== startup.sh finished at $(date -u +%Y-%m-%dT%H:%M:%SZ) =====" >> "$DEBUG_LOG"
