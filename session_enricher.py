"""
Session enrichment helpers.

Phase C of the modernization replaced the embedding-based topic classifier
with weekly LLM-driven session tagging (see tag-sessions-runner.sh). This
module is now thin:

  - load_session_tags()       — read $RETRO_DAILY_DATA/session-tags.json
  - extractive_summary(msgs)  — pick a few representative user messages

The summary uses a longest-unique heuristic — no model dependency. The old
hand-curated BUILTIN_TOPIC_LABELS / INTERACTION_TYPE_LABELS / greedy
clustering were removed; their data files (`custom-topics.json`,
`new-topics.json`) are no longer written.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List


DATA_DIR = Path(os.environ.get("RETRO_DAILY_DATA") or (Path.home() / ".claude" / "metrics"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SESSION_TAGS_FILE = DATA_DIR / "session-tags.json"


def load_session_tags() -> Dict[str, Dict[str, str]]:
    """
    Load the most recent LLM-derived session tags.
    Returns a {session_id: {topic, interaction_type}} dict, empty if the
    file is missing or malformed (caller should treat that as "no tags yet").
    """
    if not SESSION_TAGS_FILE.exists():
        return {}
    try:
        with open(SESSION_TAGS_FILE) as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for entry in payload.get("tags", []):
        sid = entry.get("id")
        if not sid:
            continue
        out[sid] = {
            "topic": str(entry.get("topic") or "untagged"),
            "interaction_type": str(entry.get("interaction_type") or "exploration"),
        }
    return out


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")


def _token_set(s: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(s)}


def extractive_summary(user_messages: List[str], top_k: int = 3) -> List[str]:
    """
    Pick `top_k` representative user messages.

    Heuristic: prefer longer messages and skip near-duplicates (>=70% token
    overlap with an already-selected message). This is a non-ML stand-in for
    the previous centroid-cosine method — keeps cost down and avoids loading
    a sentence-transformer just for this.
    """
    candidates = [m.strip() for m in user_messages if len(m.strip()) > 15]
    if not candidates:
        return []
    # Sort by length descending — longer messages are usually more informative.
    candidates.sort(key=len, reverse=True)

    selected: List[str] = []
    selected_tokens: List[set[str]] = []
    for msg in candidates:
        toks = _token_set(msg)
        is_dup = False
        for prev in selected_tokens:
            if not prev or not toks:
                continue
            overlap = len(toks & prev) / min(len(toks), len(prev))
            if overlap >= 0.70:
                is_dup = True
                break
        if not is_dup:
            selected.append(msg[:120])
            selected_tokens.append(toks)
        if len(selected) >= top_k:
            break
    return selected
