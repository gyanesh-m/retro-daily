# Shared path resolution for retro-daily shell scripts.
# Source this from each script: `source "$(dirname "${BASH_SOURCE[0]}")/_paths.sh"`
#
# RETRO_DAILY_HOME — directory containing the scripts (read-only).
#                     Defaults to the sourcing script's own directory.
# RETRO_DAILY_DATA — directory for mutable state (logs, store, results).
#                     Defaults to ~/.claude/metrics, preserving the legacy layout.
: "${RETRO_DAILY_HOME:=$(cd "$(dirname "${BASH_SOURCE[1]:-$0}")" && pwd)}"
: "${RETRO_DAILY_DATA:=$HOME/.claude/metrics}"
mkdir -p "$RETRO_DAILY_DATA"
export RETRO_DAILY_HOME RETRO_DAILY_DATA
