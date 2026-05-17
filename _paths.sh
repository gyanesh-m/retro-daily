# Shared path resolution for claude-daily shell scripts.
# Source this from each script: `source "$(dirname "${BASH_SOURCE[0]}")/_paths.sh"`
#
# CLAUDE_DAILY_HOME — directory containing the scripts (read-only).
#                     Defaults to the sourcing script's own directory.
# CLAUDE_DAILY_DATA — directory for mutable state (logs, store, results).
#                     Defaults to ~/.claude/metrics, preserving the legacy layout.
: "${CLAUDE_DAILY_HOME:=$(cd "$(dirname "${BASH_SOURCE[1]:-$0}")" && pwd)}"
: "${CLAUDE_DAILY_DATA:=$HOME/.claude/metrics}"
mkdir -p "$CLAUDE_DAILY_DATA"
export CLAUDE_DAILY_HOME CLAUDE_DAILY_DATA
