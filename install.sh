#!/usr/bin/env bash
# claude-daily installer — copies scripts to ~/.claude/metrics/ and registers the SessionStart hook.
set -euo pipefail

DEST="${HOME}/.claude/metrics"
SETTINGS="${HOME}/.claude/settings.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_CMD="bash ${DEST}/startup.sh"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
info() { printf "  • %s\n" "$1"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$1"; }

bold "claude-daily installer"

# 1. Source check — installer must run from a clone, or via curl-pipe with a known set of files.
FILES=(_paths.sh startup.sh daily-insights.sh generate-metrics.py metric_advisor.py
       prompt_classifier.py session_enricher.py
       scout.sh scout-runner.sh scout-review.sh scout-browse.sh)

if [[ ! -f "${SCRIPT_DIR}/startup.sh" ]]; then
  warn "Run from a cloned repo: git clone https://github.com/gyanesh-m/claude-daily.git && cd claude-daily && ./install.sh"
  exit 1
fi

# 2. Copy scripts.
mkdir -p "${DEST}"
for f in "${FILES[@]}"; do
  cp "${SCRIPT_DIR}/${f}" "${DEST}/${f}"
  chmod +x "${DEST}/${f}" 2>/dev/null || true
done
ok "Copied ${#FILES[@]} files to ${DEST}"

# 3. Register the SessionStart hook in settings.json.
mkdir -p "$(dirname "${SETTINGS}")"
[[ -f "${SETTINGS}" ]] || echo '{}' > "${SETTINGS}"

if ! command -v jq >/dev/null 2>&1; then
  warn "jq not found — add this to ${SETTINGS} manually:"
  cat <<EOF
  {
    "hooks": {
      "SessionStart": [
        { "matcher": "*", "hooks": [
          { "type": "command", "command": "${HOOK_CMD}", "timeout": 40,
            "statusMessage": "Loading session analytics..." }
        ]}
      ]
    }
  }
EOF
  exit 0
fi

# Idempotent: skip if a SessionStart hook already runs startup.sh.
if jq -e --arg cmd "${HOOK_CMD}" \
   '.hooks.SessionStart // [] | .[]?.hooks // [] | .[]? | select(.command == $cmd)' \
   "${SETTINGS}" >/dev/null 2>&1; then
  ok "SessionStart hook already registered — nothing to do"
else
  TMP="$(mktemp)"
  jq --arg cmd "${HOOK_CMD}" '
    .hooks //= {} |
    .hooks.SessionStart //= [] |
    .hooks.SessionStart += [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": $cmd,
        "timeout": 40,
        "statusMessage": "Loading session analytics..."
      }]
    }]
  ' "${SETTINGS}" > "${TMP}"
  mv "${TMP}" "${SETTINGS}"
  ok "Registered SessionStart hook in ${SETTINGS}"
fi

bold "Done — open a new Claude Code session to see the dashboard."
