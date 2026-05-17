#!/bin/bash
# tag-sessions-runner.sh — Headless worker. Builds a digest of recent
# Claude Code sessions, asks `claude -p` to label each with a topic +
# interaction type, and writes the labels to session-tags.json.
#
# Invoked by tag-sessions.sh via nohup.
set -u
trap '' HUP

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_paths.sh"

RESULTS_FILE="$RETRO_DAILY_DATA/session-tags.json"
HISTORY_FILE="$RETRO_DAILY_DATA/analysis-history.json"
LOG="$RETRO_DAILY_DATA/tag-sessions.log"
LOCK="$RETRO_DAILY_DATA/.tag-sessions.lock"
DIGEST_FILE="/tmp/claude-tag-digest-$$.json"
TMP_RESULTS="/tmp/claude-tag-results-$$.json"

log() { echo "[$(date +%H:%M:%S)] $*" >> "$LOG"; }

# Lock check.
if [ -f "$LOCK" ]; then
  pid=$(cat "$LOCK" 2>/dev/null || echo "")
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    log "tag-sessions-runner: another instance (pid=$pid) running, aborting"
    exit 0
  fi
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK" "$DIGEST_FILE"' EXIT

TODAY=$(date +%Y-%m-%d)
SINCE_DAYS=${TAG_SINCE_DAYS:-30}
MAX_SESSIONS=${TAG_MAX_SESSIONS:-80}

log "tag-sessions-runner: building digest (since=${SINCE_DAYS}d, max=${MAX_SESSIONS})"

# Build the session digest in Python — much cleaner than shell + jq for JSONL parsing.
PROJECTS_DIR="$HOME/.claude/projects"
DIGEST_FILE="$DIGEST_FILE" SINCE_DAYS="$SINCE_DAYS" MAX_SESSIONS="$MAX_SESSIONS" \
PROJECTS_DIR="$PROJECTS_DIR" \
python3 <<'PYEOF'
import json, os, sys
from datetime import datetime, timedelta
from pathlib import Path

projects_dir = Path(os.environ["PROJECTS_DIR"])
since_days = int(os.environ["SINCE_DAYS"])
max_sessions = int(os.environ["MAX_SESSIONS"])
out_path = Path(os.environ["DIGEST_FILE"])
cutoff = datetime.now() - timedelta(days=since_days)

if not projects_dir.exists():
    print(f"projects dir missing: {projects_dir}", file=sys.stderr)
    sys.exit(1)

def project_name(path: Path) -> str:
    """`-Users-foo-dev-github-com-bar-baz` -> `bar-baz`."""
    parts = path.name.strip("-").split("-")
    for i, p in enumerate(parts):
        if p in ("github", "gitlab", "bitbucket") and i + 1 < len(parts):
            return "-".join(parts[i + 2:]) or path.name
    return parts[-1] if parts else path.name

def extract_user_msgs(jsonl: Path, max_msgs: int = 6, max_chars: int = 240) -> list[str]:
    msgs = []
    try:
        with open(jsonl) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") != "user":
                    continue
                msg = rec.get("message", {})
                content = msg.get("content")
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    parts = [p.get("text", "") for p in content
                             if isinstance(p, dict) and p.get("type") == "text"]
                    text = " ".join(p for p in parts if p)
                else:
                    continue
                text = text.strip()
                if not text or text.startswith("<") or text.startswith("[Request interrupted"):
                    continue
                msgs.append(text[:max_chars])
                if len(msgs) >= max_msgs:
                    break
    except OSError:
        pass
    return msgs

sessions = []
for proj_dir in projects_dir.iterdir():
    if not proj_dir.is_dir():
        continue
    proj = project_name(proj_dir)
    for jsonl in proj_dir.glob("*.jsonl"):
        mtime = datetime.fromtimestamp(jsonl.stat().st_mtime)
        if mtime < cutoff:
            continue
        msgs = extract_user_msgs(jsonl)
        if not msgs:
            continue
        sessions.append({
            "id": jsonl.stem,
            "project": proj,
            "date": mtime.strftime("%Y-%m-%d"),
            "msgs": msgs,
        })

sessions.sort(key=lambda s: s["date"], reverse=True)
sessions = sessions[:max_sessions]

out_path.write_text(json.dumps({"sessions": sessions}, indent=2))
print(f"digest: {len(sessions)} sessions written to {out_path}")
PYEOF

DIGEST_COUNT=$(python3 -c "import json; print(len(json.load(open('$DIGEST_FILE'))['sessions']))" 2>/dev/null || echo 0)
if [ "$DIGEST_COUNT" -eq 0 ]; then
  log "no sessions to tag, exiting"
  exit 0
fi
log "digest has $DIGEST_COUNT sessions"

# Build the prompt. Claude reads the digest from disk to keep the prompt small.
PROMPT=$(cat <<PROMPT_EOF
You are an unattended session tagger. Read the JSON digest at $DIGEST_FILE.
Each session has: id, project, date, msgs (first few user messages, truncated).

For each session, decide:
  - "topic": a short noun phrase (1-4 words) describing what the user worked on.
    Examples: "iOS Live Activities", "Postgres migrations", "Tauri build setup",
    "GitHub Actions debugging", "marketing copy", "voice mode skill".
    Be specific to the actual content — don't use generic labels like "coding".
  - "interaction_type": exactly one of:
      feature_build | bug_fix | refactor | exploration | configuration |
      testing | documentation | code_review

Use the Write tool to create the file $TMP_RESULTS with this exact schema:

{
  "date": "$TODAY",
  "n_sessions": <count>,
  "tags": [
    { "id": "<session id>", "topic": "<short noun phrase>",
      "interaction_type": "<one of the labels above>" }
  ]
}

Rules:
- Output ONE entry per input session, in the same order.
- "topic" must reflect the specific work, not a category.
- If a session has very little content (< 3 short messages), set topic to "trivial".
- Do not print additional commentary after writing.
PROMPT_EOF
)

log "invoking claude -p (Read+Write only, no network)"
export CLAUDE_CODE_DISABLE_SESSION_START_HOOK=1
# --dangerously-skip-permissions is required when third-party PreToolUse
# hooks (e.g. Sage) are installed — without it they return "ask" against
# an unattended session and the runner exits with empty output and
# terminal_reason=hook_stopped. --permission-mode bypassPermissions only
# bypasses Claude's own checks, not third-party hooks. See scout-runner.sh
# for the full diagnosis.
CLAUDE_OUT=$(claude -p \
  --setting-sources project \
  --dangerously-skip-permissions \
  --allowedTools "Read Write" \
  --append-system-prompt "You are an unattended background tagger. Only use Read and Write. Read the digest at $DIGEST_FILE; write ONLY to $TMP_RESULTS. Be decisive; skip clarifying questions." \
  "$PROMPT" 2>&1) || {
    log "claude -p failed (exit $?). last 40 lines:"
    echo "$CLAUDE_OUT" | tail -40 >> "$LOG"
    exit 1
  }

log "claude -p completed. last 40 lines:"
echo "$CLAUDE_OUT" | tail -40 >> "$LOG"

if [ ! -f "$TMP_RESULTS" ]; then
  log "WARNING: temp results not written ($TMP_RESULTS)"
  exit 1
fi
if ! python3 -c "import json; json.load(open('$TMP_RESULTS'))" 2>/dev/null; then
  log "WARNING: $TMP_RESULTS is not valid JSON"
  cp "$TMP_RESULTS" "$LOG.bad-results.json" 2>/dev/null
  rm -f "$TMP_RESULTS"
  exit 1
fi

# Archive previous results.
ARCHIVE_DIR="$RETRO_DAILY_DATA/session-tags-archive"
mkdir -p "$ARCHIVE_DIR"
if [ -f "$RESULTS_FILE" ]; then
  PREV_DATE=$(python3 -c "import json; print(json.load(open('$RESULTS_FILE')).get('date','unknown'))" 2>/dev/null || echo "unknown")
  cp "$RESULTS_FILE" "$ARCHIVE_DIR/$PREV_DATE-$(date +%H%M%S).json" \
    && log "archived previous results"
fi

mv "$TMP_RESULTS" "$RESULTS_FILE"
log "moved results into $RESULTS_FILE"

# Update analysis-history.json with last tagging date.
python3 <<PYEOF
import json
from pathlib import Path
h_path = Path("$HISTORY_FILE")
if h_path.exists():
    h = json.load(open(h_path))
else:
    h = {}
h["last_session_tagging"] = "$TODAY"
json.dump(h, open(h_path, "w"), indent=2)
PYEOF

log "analysis-history.json updated (last_session_tagging=$TODAY)"
log "tag-sessions-runner: done"
