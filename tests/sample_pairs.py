#!/usr/bin/env python3
"""
Bootstrap a *private* eval set by sampling consecutive user-message pairs
from your local Claude Code session JSONLs (~/.claude/projects/).

The sampled file is gitignored — it stays on your machine. After labeling,
keep it as `tests/eval.local.json` and pass --eval tests/eval.local.json
to eval_classifier.py.

Usage:
    python3 tests/sample_pairs.py                    # writes tests/eval.local-unlabeled.json
    python3 tests/sample_pairs.py --n 80             # sample size
    python3 tests/sample_pairs.py --since 30         # only sessions from last N days
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path


def find_jsonls(projects_dir: Path, since_days: int | None) -> list[Path]:
    cutoff = datetime.now() - timedelta(days=since_days) if since_days else None
    out = []
    for jsonl in projects_dir.rglob("*.jsonl"):
        if cutoff and datetime.fromtimestamp(jsonl.stat().st_mtime) < cutoff:
            continue
        out.append(jsonl)
    return out


def extract_user_messages(jsonl: Path) -> list[str]:
    """Yield the text content of `user` role messages, in order."""
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
                # Claude Code session schema: {type: "user", message: {role, content}}
                if rec.get("type") != "user":
                    continue
                msg = rec.get("message", {})
                content = msg.get("content")
                # content can be a string or a list of {type, text} parts
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
                    text = " ".join(p for p in parts if p)
                else:
                    continue
                text = text.strip()
                if text and not text.startswith("<") and len(text) < 4000:
                    msgs.append(text)
    except OSError:
        pass
    return msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects-dir", default=str(Path.home() / ".claude" / "projects"))
    ap.add_argument("--n", type=int, default=80, help="Number of pairs to sample")
    ap.add_argument("--since", type=int, default=None, help="Only sessions from last N days")
    ap.add_argument("--out", default=str(Path(__file__).parent / "eval.local-unlabeled.json"))
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    projects_dir = Path(args.projects_dir)
    if not projects_dir.exists():
        print(f"projects dir not found: {projects_dir}", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    jsonls = find_jsonls(projects_dir, args.since)
    print(f"Found {len(jsonls)} session JSONLs")

    all_pairs = []
    for jsonl in jsonls:
        msgs = extract_user_messages(jsonl)
        for i in range(len(msgs) - 1):
            all_pairs.append({"prompt": msgs[i], "reaction": msgs[i + 1], "label": "?"})

    print(f"Extracted {len(all_pairs)} consecutive (prompt, reaction) pairs")

    if not all_pairs:
        print("Nothing to sample. Exiting.", file=sys.stderr)
        return 1

    sample = rng.sample(all_pairs, min(args.n, len(all_pairs)))
    out_path = Path(args.out)
    out_path.write_text(json.dumps(sample, indent=2))
    print(f"Wrote {len(sample)} unlabeled pairs to {out_path}")
    print("Next: hand-label each entry's `label` field, save as eval.local.json,")
    print("then run: python3 tests/eval_classifier.py --eval tests/eval.local.json")


if __name__ == "__main__":
    sys.exit(main())
