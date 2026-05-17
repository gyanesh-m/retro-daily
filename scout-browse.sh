#!/bin/bash
# scout-browse.sh — Interactive viewer for all scout findings (current + archived).
# Pipes a formatted, colorized listing to `less -R` so you can search with `/regex`.
#
# Usage:
#   bash scout-browse.sh           # browse all findings
#   bash scout-browse.sh <query>   # pre-filter by regex, then browse
set -e
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_paths.sh"

CURRENT="$CLAUDE_DAILY_DATA/scout-results.json"
ARCHIVE_DIR="$CLAUDE_DAILY_DATA/scout-archive"

FILTER="${1:-}"

CLAUDE_DAILY_DATA="$CLAUDE_DAILY_DATA" python3 - "$FILTER" <<'PYEOF' | less -R
import json, sys, re, os, glob
from pathlib import Path

flt = sys.argv[1] if len(sys.argv) > 1 else ""
flt_re = re.compile(flt, re.IGNORECASE) if flt else None

def _c(code): return f"\033[{code}m"
RESET = _c(0); BOLD = _c(1); DIM = _c(2)
CYAN = _c(36); BRIGHT_CYAN = _c(96); BRIGHT_WHITE = _c(97)
BRIGHT_YELLOW = _c(93); BRIGHT_GREEN = _c(92); BRIGHT_MAGENTA = _c(95)
RULE = 72

metrics_dir = Path(os.environ["CLAUDE_DAILY_DATA"])
archive_dir = metrics_dir / "scout-archive"
current = metrics_dir / "scout-results.json"

files = []
if current.exists():
    files.append(("current", current))
if archive_dir.exists():
    for f in sorted(archive_dir.glob("*.json"), reverse=True):
        files.append(("archived", f))

# Header
print(f"{BRIGHT_CYAN}{BOLD}{' '.join('SCOUT BROWSER')}{RESET}")
print(f"{BRIGHT_CYAN}{'━' * RULE}{RESET}")
print(f"{DIM}{len(files)} scout run(s) total · press / to search · q to quit{RESET}")
if flt:
    print(f"{DIM}pre-filter: {BRIGHT_YELLOW}{flt}{RESET}")
print()

def matches(f, rec, tag):
    if flt_re is None: return True
    blob = " ".join([
        tag, rec.get("query",""),
        f.get("title",""), f.get("summary",""),
        f.get("actionable",""), f.get("url","")
    ])
    return bool(flt_re.search(blob))

total_findings = 0
matched_findings = 0
for tag, path in files:
    try:
        data = json.load(open(path))
    except Exception as e:
        print(f"{DIM}  [skip] {path.name}: {e}{RESET}")
        continue

    date = data.get("date", "?")
    weak = ", ".join(data.get("weak_metrics", []))
    tag_col = BRIGHT_GREEN if tag == "current" else DIM
    header = f"{tag_col}[{tag}]{RESET} {BOLD}{date}{RESET} {DIM}· {weak}{RESET}"

    block_lines = [header]
    any_match_in_file = False
    for rec in data.get("recommendations", []):
        q = rec.get("query", "")
        q_lines = [f"  {BRIGHT_YELLOW}●{RESET} {BOLD}{q}{RESET}"]
        any_match_in_query = False
        for f in rec.get("findings", []):
            total_findings += 1
            if not matches(f, rec, tag):
                continue
            matched_findings += 1
            any_match_in_query = True
            any_match_in_file = True
            title = f.get("title", "untitled")
            summary = f.get("summary", "")
            actionable = f.get("actionable", "")
            url = f.get("url", "")
            title_col = BRIGHT_MAGENTA if title.startswith("[trending]") else BRIGHT_WHITE
            q_lines.append(f"    {title_col}{title}{RESET}")
            if summary:
                q_lines.append(f"      {DIM}{summary}{RESET}")
            if actionable:
                q_lines.append(f"      {BRIGHT_GREEN}→{RESET} {actionable}")
            if url:
                q_lines.append(f"      {DIM}{url}{RESET}")
        if any_match_in_query:
            block_lines.extend(q_lines)
            block_lines.append("")
    if any_match_in_file:
        print("\n".join(block_lines))
        print(f"{DIM}{'─' * RULE}{RESET}")
        print()

if flt:
    print(f"{DIM}matched {matched_findings}/{total_findings} findings{RESET}")
else:
    print(f"{DIM}{total_findings} findings across {len(files)} scout run(s){RESET}")
PYEOF
