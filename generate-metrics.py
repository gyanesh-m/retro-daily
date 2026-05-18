#!/usr/bin/env python3
"""
Generate daily Claude Code metrics from JSONL session logs across ALL projects.
Runs once per day, processes only new dates, stores state under $RETRO_DAILY_DATA
(default: ~/.claude/metrics).
Outputs brief insights to stdout for the SessionStart hook.
"""
import json, os, re, sys, glob
from datetime import datetime, date, timedelta
from collections import defaultdict, Counter
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
# CODE_DIR is where the scripts live; DATA_DIR is where mutable state lives.
# Defaults keep the legacy single-dir layout (~/.claude/metrics) intact.
CODE_DIR = Path(os.environ.get("RETRO_DAILY_HOME") or Path(__file__).resolve().parent)
DATA_DIR = Path(os.environ.get("RETRO_DAILY_DATA") or (CLAUDE_DIR / "metrics"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
METRICS_DIR = DATA_DIR  # backwards-compat alias for any external readers
STORE_FILE = DATA_DIR / "metrics-store.json"
LAST_RUN_FILE = DATA_DIR / "last-run-date.txt"
VENV_PYTHON = DATA_DIR / ".venv" / "bin" / "python3"

# Lazy-loaded classifier (only initialized if needed)
_classifier = None

def get_classifier():
    global _classifier
    if _classifier is None:
        sys.path.insert(0, str(CODE_DIR))
        from prompt_classifier import PromptClassifier
        _classifier = PromptClassifier()
    return _classifier


# Per-model pricing ($/1M tokens). base_in/base_out are <=200K prompts;
# *_1m are the long-context premium tier (>200K input tokens in a single call).
# cache_read = 0.1x base_in; cache_create (5m ephemeral, Claude Code default) = 1.25x base_in.
PRICING = {
    "opus":    {"in": 15.0, "out": 75.0,  "in_1m": 30.0, "out_1m": 112.5},
    "sonnet":  {"in": 3.0,  "out": 15.0,  "in_1m": 6.0,  "out_1m": 22.5},
    "haiku":   {"in": 1.0,  "out": 5.0,   "in_1m": 1.0,  "out_1m": 5.0},  # no 1m tier
    "haiku35": {"in": 0.8,  "out": 4.0,   "in_1m": 0.8,  "out_1m": 4.0},
}

# Cost numbers are computed at API list price; they are NOT what you actually pay
# if you're on a Claude subscription. RETRO_DAILY_PLAN_LABEL lets users name their
# plan so the footer reads, e.g., "capped by Claude Max $100/mo". Unset = generic.
PLAN_LABEL = os.environ.get("RETRO_DAILY_PLAN_LABEL", "").strip()

def model_family(model_id: str) -> str:
    m = (model_id or "").lower()
    if "opus" in m: return "opus"
    if "sonnet" in m: return "sonnet"
    if "haiku-3" in m or "haiku-3-5" in m: return "haiku35"
    if "haiku" in m: return "haiku"
    return "sonnet"  # safe default

def message_cost(model_id: str, usage: dict) -> float:
    fam = model_family(model_id)
    p = PRICING[fam]
    inp = usage.get("input_tokens", 0)
    out = usage.get("output_tokens", 0)
    cr  = usage.get("cache_read_input_tokens", 0)
    cc  = usage.get("cache_creation_input_tokens", 0)
    # Detect 1M-context premium: prompt size (all input-side tokens) > 200K
    prompt_total = inp + cr + cc
    if prompt_total > 200_000:
        in_rate, out_rate = p["in_1m"], p["out_1m"]
    else:
        in_rate, out_rate = p["in"], p["out"]
    return (
        inp * in_rate / 1e6 +
        cc  * in_rate * 1.25 / 1e6 +
        cr  * in_rate * 0.10 / 1e6 +
        out * out_rate / 1e6
    )


def load_store():
    if STORE_FILE.exists():
        with open(STORE_FILE) as f:
            return json.load(f)
    return {"daily": {}, "cumulative": {}, "by_project": {}}


def save_store(store):
    with open(STORE_FILE, "w") as f:
        json.dump(store, f, indent=2)


def project_display_name(proj_dir_name):
    """Convert project dir name to a readable name."""
    parts = proj_dir_name.strip("-").split("-")
    # Find the last meaningful segment (after github-com or similar)
    for i, p in enumerate(parts):
        if p == "com" and i + 1 < len(parts):
            return "-".join(parts[i + 1:])
    # Fallback: last 2 segments
    return "-".join(parts[-2:]) if len(parts) > 1 else parts[-1]


def process_session(filepath):
    """Extract metrics from a single JSONL session file."""
    messages = []
    tool_counts = defaultdict(int)
    token_usage = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
    session_cost = 0.0
    tokens_by_family = {"opus": 0, "sonnet": 0, "haiku": 0, "haiku35": 0}
    tool_errors = 0
    tool_error_types = defaultdict(int)
    branches = set()
    max_context_tokens = 0
    compacted = False

    with open(filepath) as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except Exception:
                continue

            # Extract branch from entry header
            branch = entry.get("gitBranch")
            if branch:
                branches.add(branch)

            msg = entry.get("message", {})
            role = msg.get("role", "")
            ts = entry.get("timestamp", "")

            # Extract token usage from assistant messages
            if role == "assistant":
                usage = msg.get("usage", {})
                if usage:
                    token_usage["input"] += usage.get("input_tokens", 0)
                    token_usage["output"] += usage.get("output_tokens", 0)
                    token_usage["cache_read"] += usage.get("cache_read_input_tokens", 0)
                    token_usage["cache_create"] += usage.get("cache_creation_input_tokens", 0)
                    # Track peak context size
                    ctx = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
                    if ctx > max_context_tokens:
                        max_context_tokens = ctx
                    # Per-message cost using the message's actual model
                    model_id = msg.get("model", "")
                    session_cost += message_cost(model_id, usage)
                    fam = model_family(model_id)
                    tokens_by_family[fam] += (
                        usage.get("input_tokens", 0)
                        + usage.get("output_tokens", 0)
                        + usage.get("cache_read_input_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0)
                    )

            if role not in ("user", "assistant") or not ts:
                continue

            text = ""
            content = msg.get("content", [])
            has_tool_use = False
            has_tool_result = False
            tool_denied = False

            if isinstance(content, str):
                text = content
                if role == "user" and "<command-name>/compact</command-name>" in content:
                    compacted = True
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text += block.get("text", "") + " "
                        elif block.get("type") == "tool_use":
                            has_tool_use = True
                            tool_counts[block.get("name", "unknown")] += 1
                        elif block.get("type") == "tool_result":
                            has_tool_result = True
                            is_error = block.get("is_error", False)
                            c = block.get("content", "")
                            cs = c if isinstance(c, str) else " ".join(
                                sub.get("text", "") for sub in c if isinstance(sub, dict)
                            )
                            if "denied" in cs.lower() or "not allowed" in cs.lower():
                                tool_denied = True
                            # Track tool errors
                            if is_error:
                                tool_errors += 1
                                cl = cs.lower()
                                if "has not been read" in cl or "file not read" in cl:
                                    tool_error_types["file_not_read"] += 1
                                elif "denied" in cl or "permission" in cl:
                                    tool_error_types["permission"] += 1
                                elif "command failed" in cl or "exit code" in cl:
                                    tool_error_types["command_failed"] += 1
                                else:
                                    tool_error_types["other"] += 1

            messages.append({
                "role": role, "ts": ts, "text": text.strip()[:300],
                "has_tool_use": has_tool_use, "has_tool_result": has_tool_result,
                "tool_denied": tool_denied,
            })

    # Permission waits
    auto = human = denied = 0
    waits = []
    for i in range(len(messages) - 1):
        if messages[i]["role"] == "assistant" and messages[i]["has_tool_use"]:
            if messages[i + 1]["role"] == "user" and messages[i + 1]["has_tool_result"]:
                try:
                    t1 = datetime.fromisoformat(messages[i]["ts"].replace("Z", "+00:00"))
                    t2 = datetime.fromisoformat(messages[i + 1]["ts"].replace("Z", "+00:00"))
                    gap = (t2 - t1).total_seconds()
                    if gap < 2:
                        auto += 1
                    elif gap < 600:
                        human += 1
                        waits.append(gap)
                except Exception:
                    pass
                if messages[i + 1]["tool_denied"]:
                    denied += 1

    # Course corrections
    correction_patterns = [
        r'\bno[,.]?\s', r"\bdon'?t\b", r'\bstop\b', r'\bwrong\b',
        r'\bactually\b', r'\binstead\b', r'\bnot that\b', r"\bthat'?s not\b",
        r'\bcancel\b', r'\bremove that\b', r'\bundo\b', r'\brevert\b',
        r'\bpointless\b', r'\bunnecessary\b', r'\bwhy is there\b', r'\bwhy did you\b',
    ]
    # Exclude synthetic/command-wrapper pseudo-messages (slash-commands, bash stdin/stdout
     # capture, local command caveats, prompt-submit hooks) — they aren't real user input.
    _SYNTH_TAG_RE = re.compile(
        r'^\s*<(?:local-command-(?:caveat|stdout|stderr)|command-(?:name|message|args)|'
        r'bash-(?:input|stdout|stderr)|user-prompt-submit-hook|system-reminder|'
        r'task-notification|output-file|tool-use-id|task-id)\b',
        re.IGNORECASE,
    )
    # Count real user turns (non-synthetic, non-tool-result)
    user_turns = 0
    for msg_entry in messages:
        if msg_entry["role"] != "user":
            continue
        if msg_entry.get("has_tool_result"):
            continue
        if msg_entry["text"] and _SYNTH_TAG_RE.match(msg_entry["text"]):
            continue
        user_turns += 1

    user_texts = [
        m["text"] for m in messages
        if m["role"] == "user" and m["text"] and not m["has_tool_result"]
        and not _SYNTH_TAG_RE.match(m["text"])
    ]
    corrections = 0
    for text in user_texts:
        for pat in correction_patterns:
            if re.search(pat, text.lower()):
                corrections += 1
                break

    reads = sum(v for k, v in tool_counts.items() if k in ("Read", "Grep", "Glob"))
    edits = sum(v for k, v in tool_counts.items() if k in ("Edit", "Write"))
    bash = tool_counts.get("Bash", 0)
    agents = tool_counts.get("Agent", 0)
    mcp = sum(v for k, v in tool_counts.items() if k.startswith("mcp__"))

    return {
        "size_kb": os.path.getsize(filepath) // 1024,
        "total_tools": sum(tool_counts.values()),
        "user_msgs": len([m for m in messages if m["role"] == "user" and not m["has_tool_result"]]),
        "reads": reads, "edits": edits, "bash": bash, "agents": agents, "mcp": mcp,
        "auto_approved": auto, "human_interrupted": human, "denied": denied,
        "median_wait": round(sorted(waits)[len(waits) // 2], 1) if waits else 0,
        "corrections": corrections,
        "correction_user_msgs": len(user_texts),
        "user_texts": user_texts,  # For embedding classifier
        # New enrichment fields
        "token_usage": token_usage,
        "session_cost": round(session_cost, 4),
        "tokens_by_family": tokens_by_family,
        "tool_errors": tool_errors,
        "tool_error_types": dict(tool_error_types),
        "branches": list(branches),
        "max_context_tokens": max_context_tokens,
        "user_turns": user_turns,
        "compacted": compacted,
    }


def _refresh_cumulative(store):
    """Recompute cumulative metrics from all daily data. Safe to call anytime."""
    all_days = store.get("daily", {})
    if not all_days:
        return

    total_auto = sum(d["auto_approved"] for d in all_days.values())
    total_human = sum(d["human_interrupted"] for d in all_days.values())

    cum_class = {"APPROVAL": 0, "REFINEMENT": 0, "CORRECTION": 0, "NEW_TASK": 0}
    for day in all_days.values():
        for cat in cum_class:
            cum_class[cat] += day.get("prompt_classifications", {}).get(cat, 0)
    cum_pairs = sum(cum_class.values())
    cum_successful = cum_class["APPROVAL"] + cum_class["NEW_TASK"]

    total_tool_errors = sum(d.get("tool_errors", 0) for d in all_days.values())
    total_tools_all = sum(d["total_tools"] for d in all_days.values())
    total_long_sessions = sum(d.get("long_sessions", 0) for d in all_days.values())
    total_long_compacted = sum(d.get("long_compacted", 0) for d in all_days.values())
    total_cost = sum(d.get("estimated_cost", 0) for d in all_days.values())
    total_tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
    for d in all_days.values():
        tu = d.get("token_usage", {})
        for k in total_tokens:
            total_tokens[k] += tu.get(k, 0)

    cum_topics = Counter()
    cum_interaction_types = Counter()
    for day in all_days.values():
        for topic, count in day.get("topics", {}).items():
            cum_topics[topic] += count
        for itype, count in day.get("interaction_types", {}).items():
            cum_interaction_types[itype] += count

    store["cumulative"] = {
        "total_sessions": sum(d["sessions"] for d in all_days.values()),
        "total_tools": total_tools_all,
        "total_user_msgs": sum(d["user_msgs"] for d in all_days.values()),
        "total_size_mb": round(sum(d["size_kb"] for d in all_days.values()) / 1024, 1),
        "active_days": len(all_days),
        "edit_read_ratio": round(
            sum(d["edits"] for d in all_days.values()) /
            max(sum(d["reads"] for d in all_days.values()), 1), 2
        ),
        "correction_rate": round(
            sum(d["corrections"] for d in all_days.values()) * 100 /
            max(sum(d["correction_user_msgs"] for d in all_days.values()), 1), 1
        ),
        "auto_rate": round(total_auto * 100 / max(total_auto + total_human, 1), 1),
        "prompt_classifications": cum_class,
        "first_try_rate": round(cum_successful * 100 / max(cum_pairs, 1), 1),
        "total_estimated_cost": round(total_cost, 2),
        "total_tool_errors": total_tool_errors,
        "tool_error_rate": round(total_tool_errors * 100 / max(total_tools_all, 1), 1),
        "ctx_compact_rate": (
            round(total_long_compacted * 100 / total_long_sessions, 1)
            if total_long_sessions > 0 else None
        ),
        "long_sessions_total": total_long_sessions,
        "top_topics": dict(cum_topics.most_common(5)),
        "top_interaction_types": dict(cum_interaction_types.most_common(5)),
        "total_tokens": total_tokens,
    }


def _backfill_ctx_hygiene(store):
    """One-time migration: scan JSONL files to add long_sessions/long_compacted
    to existing daily store entries that predate the ctx_compact_rate metric.
    Runs in O(files) time — no embedding classifier needed."""
    import re as _re
    _LONG_TURN_THRESHOLD = 40
    _SYNTH_RE = _re.compile(
        r'^\s*<(?:local-command-(?:caveat|stdout|stderr)|command-(?:name|message|args)|'
        r'bash-(?:input|stdout|stderr)|user-prompt-submit-hook|system-reminder|'
        r'task-notification|output-file|tool-use-id|task-id)\b',
        _re.IGNORECASE,
    )

    # Build a date→[jsonl_paths] map from PROJECTS_DIR
    date_files = defaultdict(list)
    if not PROJECTS_DIR.exists():
        return
    for proj_dir in PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        for f in proj_dir.glob("*.jsonl"):
            d = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
            date_files[d].append(str(f))

    changed = False
    for d, day_data in store.get("daily", {}).items():
        if "long_sessions" in day_data:
            continue  # already backfilled
        long_sessions = 0
        long_compacted = 0
        for filepath in date_files.get(d, []):
            if "/subagents/" in filepath:
                continue
            user_turns = 0
            session_compacted = False
            try:
                with open(filepath) as fh:
                    for line in fh:
                        try:
                            entry = json.loads(line)
                            msg = entry.get("message", {})
                            role = msg.get("role", "")
                            if role != "user":
                                continue
                            content = msg.get("content", "")
                            if isinstance(content, str):
                                if "<command-name>/compact</command-name>" in content:
                                    session_compacted = True
                                elif not _SYNTH_RE.match(content):
                                    user_turns += 1
                            elif isinstance(content, list):
                                has_tr = any(
                                    b.get("type") == "tool_result"
                                    for b in content if isinstance(b, dict)
                                )
                                if not has_tr:
                                    text = " ".join(
                                        b.get("text", "") for b in content
                                        if isinstance(b, dict) and b.get("type") == "text"
                                    )
                                    if not _SYNTH_RE.match(text) if text else True:
                                        user_turns += 1
                        except Exception:
                            continue
            except Exception:
                continue
            if user_turns >= _LONG_TURN_THRESHOLD:
                long_sessions += 1
                if session_compacted:
                    long_compacted += 1

        day_data["long_sessions"] = long_sessions
        day_data["long_compacted"] = long_compacted
        ls = long_sessions
        day_data["ctx_compact_rate"] = round(long_compacted * 100 / ls, 1) if ls > 0 else None
        changed = True

    return changed


def main():
    store = load_store()
    today = date.today()
    yesterday = today - timedelta(days=1)

    # One-time migration: backfill ctx hygiene into historical daily entries
    if _backfill_ctx_hygiene(store):
        _refresh_cumulative(store)
        save_store(store)

    # Already ran today — skip
    if LAST_RUN_FILE.exists():
        try:
            last_run = date.fromisoformat(LAST_RUN_FILE.read_text().strip())
            if last_run == today:
                return
        except Exception:
            pass

    # Scan all project directories for JSONL files
    new_data = defaultdict(lambda: defaultdict(list))  # {date: {project: [files]}}

    if not PROJECTS_DIR.exists():
        LAST_RUN_FILE.write_text(today.isoformat())
        return

    for proj_dir in PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        proj_name = project_display_name(proj_dir.name)
        for f in proj_dir.glob("*.jsonl"):
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            d = mtime.strftime("%Y-%m-%d")
            # Skip today (in-progress) and already-processed dates
            if mtime.date() >= today:
                continue
            if d in store["daily"] and d != yesterday.isoformat():
                continue
            new_data[d][proj_name].append(str(f))

    if not new_data:
        # Even with no new data, refresh cumulative in case fields are missing (schema upgrade)
        _refresh_cumulative(store)
        save_store(store)
        LAST_RUN_FILE.write_text(today.isoformat())
        print_insights(store, yesterday.isoformat())
        return

    # Load classifier once if we have data to process
    classifier = None
    has_venv = VENV_PYTHON.exists()
    if has_venv:
        try:
            classifier = get_classifier()
        except Exception as e:
            print(f"Note: Classifier unavailable ({e}), using regex fallback", file=sys.stderr)

    # Process each new day
    for d in sorted(new_data.keys()):
        day_agg = {
            "sessions": 0, "total_tools": 0, "user_msgs": 0, "size_kb": 0,
            "reads": 0, "edits": 0, "bash": 0, "agents": 0, "mcp": 0,
            "auto_approved": 0, "human_interrupted": 0, "denied": 0,
            "corrections": 0, "correction_user_msgs": 0, "projects": [],
            # Embedding-based metrics
            "prompt_classifications": {"APPROVAL": 0, "REFINEMENT": 0, "CORRECTION": 0, "NEW_TASK": 0},
            "first_try_rate": 0.0,
            # New enrichment fields
            "token_usage": {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0},
            "session_cost_sum": 0.0,
            "tokens_by_family": {"opus": 0, "sonnet": 0, "haiku": 0, "haiku35": 0},
            "tool_errors": 0, "tool_error_types": defaultdict(int),
            "branches": [], "max_context_tokens": 0,
            "long_sessions": 0, "long_compacted": 0,
        }
        all_user_texts_day = []  # Collect for classifier
        all_sessions_day = []   # (session_id, user_texts) for tag lookup + summary

        for proj_name, files in new_data[d].items():
            day_agg["sessions"] += len(files)
            if proj_name not in day_agg["projects"]:
                day_agg["projects"].append(proj_name)
            for f in files:
                s = process_session(f)
                for k in ("total_tools", "user_msgs", "size_kb", "reads", "edits",
                           "bash", "agents", "mcp", "auto_approved", "human_interrupted",
                           "denied", "corrections", "correction_user_msgs"):
                    day_agg[k] += s[k]
                # Aggregate token usage
                for tk in ("input", "output", "cache_read", "cache_create"):
                    day_agg["token_usage"][tk] += s["token_usage"][tk]
                day_agg["session_cost_sum"] += s.get("session_cost", 0.0)
                for fam, n in s.get("tokens_by_family", {}).items():
                    day_agg["tokens_by_family"][fam] = day_agg["tokens_by_family"].get(fam, 0) + n
                # Aggregate tool errors
                day_agg["tool_errors"] += s["tool_errors"]
                for etype, count in s["tool_error_types"].items():
                    day_agg["tool_error_types"][etype] += count
                # Aggregate branches
                for b in s["branches"]:
                    if b not in day_agg["branches"]:
                        day_agg["branches"].append(b)
                # Track max context
                if s["max_context_tokens"] > day_agg["max_context_tokens"]:
                    day_agg["max_context_tokens"] = s["max_context_tokens"]
                # Context hygiene: long sessions (>40 real user turns) with/without compact
                _LONG_TURN_THRESHOLD = 40
                if s.get("user_turns", 0) >= _LONG_TURN_THRESHOLD:
                    day_agg["long_sessions"] += 1
                    if s.get("compacted", False):
                        day_agg["long_compacted"] += 1
                # Collect user texts + session id per session for classifier and tag lookup
                if s["user_texts"] and len(s["user_texts"]) >= 2:
                    all_user_texts_day.append(s["user_texts"])
                    all_sessions_day.append((Path(f).stem, s["user_texts"]))

            # Track per-project cumulative
            if proj_name not in store["by_project"]:
                store["by_project"][proj_name] = {"sessions": 0, "tools": 0, "days": []}
            store["by_project"][proj_name]["sessions"] += len(files)
            store["by_project"][proj_name]["tools"] += day_agg["total_tools"]
            if d not in store["by_project"][proj_name]["days"]:
                store["by_project"][proj_name]["days"].append(d)

        # Run embedding classifier on the day's sessions
        if classifier and all_user_texts_day:
            total_pairs = 0
            for user_texts in all_user_texts_day:
                result = classifier.analyze_session(user_texts)
                for cat, count in result["classifications"].items():
                    day_agg["prompt_classifications"][cat] += count
                total_pairs += result["total_pairs"]
            successful = day_agg["prompt_classifications"]["APPROVAL"] + day_agg["prompt_classifications"]["NEW_TASK"]
            day_agg["first_try_rate"] = round(successful * 100 / max(total_pairs, 1), 1)

        # Session enrichment via LLM-derived tags + a non-ML extractive summary.
        # Tags are produced out-of-band by tag-sessions-runner.sh on a weekly
        # cadence; we just join them in here. Sessions without tags (newly
        # created since the last tagging run) count as "untagged".
        if all_sessions_day:
            try:
                sys.path.insert(0, str(CODE_DIR))
                from session_enricher import load_session_tags, extractive_summary
                tags = load_session_tags()
                day_topics = Counter()
                day_interaction_types = Counter()
                day_summaries = []
                for sid, user_texts in all_sessions_day:
                    tag = tags.get(sid)
                    if tag:
                        topic = tag.get("topic", "untagged")
                        itype = tag.get("interaction_type", "exploration")
                    else:
                        topic = "untagged"
                        itype = "exploration"
                    day_topics[topic] += 1
                    day_interaction_types[itype] += 1
                    day_summaries.extend(extractive_summary(user_texts))
                day_agg["topics"] = dict(day_topics.most_common(5))
                day_agg["interaction_types"] = dict(day_interaction_types)
                day_agg["session_summaries"] = day_summaries[:6]
            except Exception as e:
                print(f"Note: Session enrichment failed ({e})", file=sys.stderr)

        # Derived
        day_agg["edit_read_ratio"] = round(day_agg["edits"] / max(day_agg["reads"], 1), 2)
        day_agg["correction_rate"] = round(
            day_agg["corrections"] * 100 / max(day_agg["correction_user_msgs"], 1), 1
        )
        day_agg["auto_rate"] = round(
            day_agg["auto_approved"] * 100 /
            max(day_agg["auto_approved"] + day_agg["human_interrupted"], 1), 1
        )
        day_agg["tool_error_rate"] = round(
            day_agg["tool_errors"] * 100 / max(day_agg["total_tools"], 1), 1
        )
        # Context hygiene: % of long sessions that used /compact (higher_better)
        ls = day_agg["long_sessions"]
        lc = day_agg["long_compacted"]
        day_agg["ctx_compact_rate"] = round(lc * 100 / ls, 1) if ls > 0 else None
        # Estimated cost: per-message, per-model pricing (cache_create @ 1.25x base,
        # cache_read @ 0.10x base, 1M-context premium when prompt >200K tokens).
        day_agg["estimated_cost"] = round(day_agg.pop("session_cost_sum", 0.0), 2)
        # Convert defaultdict to dict for JSON serialization
        day_agg["tool_error_types"] = dict(day_agg["tool_error_types"])
        store["daily"][d] = day_agg

    _refresh_cumulative(store)

    save_store(store)
    LAST_RUN_FILE.write_text(today.isoformat())
    print_insights(store, yesterday.isoformat())


def _c(code):
    """Return ANSI escape for color code."""
    return f"\033[{code}m"

RESET  = _c(0)
BOLD   = _c(1)
DIM    = _c(2)
RED    = _c(31)
GREEN  = _c(32)
YELLOW = _c(33)
BLUE   = _c(34)
MAGENTA= _c(35)
CYAN   = _c(36)
WHITE  = _c(37)
BRIGHT_RED    = _c(91)
BRIGHT_GREEN  = _c(92)
BRIGHT_YELLOW = _c(93)
BRIGHT_BLUE   = _c(94)
BRIGHT_MAGENTA= _c(95)
BRIGHT_CYAN   = _c(96)
BRIGHT_WHITE  = _c(97)

_ANSI_RE = re.compile(r'\033\[[0-9;]*m')
_SPARK_BLOCKS = "▁▂▃▄▅▆▇█"
_RULE_WIDTH = 68


def _visible_len(s):
    return len(_ANSI_RE.sub('', s))


def _pad(s, width, align='left'):
    """Pad a string (containing ANSI codes) to `width` visible chars."""
    vl = _visible_len(s)
    if vl >= width:
        return s
    filler = ' ' * (width - vl)
    return filler + s if align == 'right' else s + filler


def _severity_color(severity):
    return {
        "BAD": BRIGHT_RED + BOLD,
        "WARN": BRIGHT_YELLOW,
        "OK": BRIGHT_GREEN,
        "GOOD": GREEN,
    }.get(severity, WHITE)


def _severity_dot(severity):
    color = _severity_color(severity)
    return f"{color}⬤{RESET}"


def _section(title, color=BRIGHT_CYAN):
    """Editorial section header: letterspaced bold label over a heavy rule."""
    spaced = ' '.join(title.upper())
    return (
        f"{color}{BOLD}{spaced}{RESET}\n"
        f"{color}{'━' * _RULE_WIDTH}{RESET}"
    )


def _spark(values, width=14):
    """Map values into a unicode sparkline."""
    vals = [v for v in values if v is not None]
    if not vals:
        return DIM + ('·' * width) + RESET
    # Take the most recent `width` values
    vals = vals[-width:]
    lo, hi = min(vals), max(vals)
    span = hi - lo
    out = []
    for v in vals:
        if span == 0:
            idx = 3  # flat line → mid block
        else:
            idx = int((v - lo) / span * (len(_SPARK_BLOCKS) - 1) + 0.5)
        out.append(_SPARK_BLOCKS[idx])
    # Left-pad with dim dots if we have fewer points than `width`
    pad = width - len(out)
    return (DIM + ('·' * pad) + RESET) + ''.join(out) if pad else ''.join(out)


def _trend_arrow(delta, direction):
    """One-char trend arrow with severity color. → = stable, ↑ = up, ↓ = down."""
    if delta is None:
        return DIM + '·' + RESET
    if abs(delta) < 0.5:
        return DIM + '→' + RESET
    improved = (delta > 0 and direction == "higher_better") or (delta < 0 and direction == "lower_better")
    color = BRIGHT_GREEN if improved else BRIGHT_RED
    char = '↑' if delta > 0 else '↓'
    return f"{color}{char}{RESET}"


def _gauge(value, warn, good, direction, width=20, severity="WARN"):
    """Horizontal gauge. Scale is [0, good] for higher_better and [0, hi] for lower_better."""
    if direction == "higher_better":
        lo = 0
        hi = good
        pct = (value - lo) / (hi - lo) if hi != lo else 0
    else:
        lo = 0
        hi = warn + (warn - good)
        pct = 1.0 - value / hi if hi != 0 else 0
    pct = max(0.0, min(1.0, pct))
    filled = int(round(pct * width))
    color = _severity_color(severity)
    return f"{color}{'█' * filled}{DIM}{'░' * (width - filled)}{RESET}"

METRIC_DISPLAY = {
    "edit_read_ratio":  "Edit / Read",
    "auto_rate":        "Auto-approve",
    "first_try_rate":   "First-try",
    "correction_rate":  "Corrections",
    "tool_error_rate":  "Tool errors",
    "ctx_compact_rate": "Ctx hygiene",
}

METRIC_SUFFIX = {
    "auto_rate": "%", "first_try_rate": "%",
    "correction_rate": "%", "tool_error_rate": "%",
    "ctx_compact_rate": "%",
}


def _metric_history(store, metric, window=14):
    """Return the metric values for the most recent `window` days (in chronological order)."""
    daily = store.get("daily", {})
    dates = sorted(daily.keys())[-window:]
    return [daily[d].get(metric) for d in dates]


def _metric_score(metric, value):
    """Normalize a metric to 0..100 where 100 = at/past `good` threshold, 0 = fully bad."""
    from metric_advisor import METRIC_THRESHOLDS
    t = METRIC_THRESHOLDS.get(metric)
    if t is None or value is None:
        return None
    good, warn, direction = t["good"], t["warn"], t["direction"]
    if direction == "higher_better":
        worst = max(0, warn - (good - warn))  # one-step past warn
        best = good
        pct = (value - worst) / (best - worst) if best != worst else 1.0
    else:
        worst = warn + (warn - good)
        best = good
        pct = 1.0 - (value - best) / (worst - best) if worst != best else 1.0
    return max(0.0, min(1.0, pct)) * 100


def _letter_grade(score):
    """Map a 0-100 composite score to a letter grade with +/- modifiers."""
    if score >= 93: return "A"
    if score >= 90: return "A-"
    if score >= 87: return "B+"
    if score >= 83: return "B"
    if score >= 80: return "B-"
    if score >= 77: return "C+"
    if score >= 73: return "C"
    if score >= 70: return "C-"
    if score >= 65: return "D+"
    if score >= 60: return "D"
    return "F"


def _grade_color(score):
    if score >= 80: return BRIGHT_GREEN + BOLD
    if score >= 70: return BRIGHT_CYAN + BOLD
    if score >= 60: return BRIGHT_YELLOW + BOLD
    return BRIGHT_RED + BOLD


def _severity_for(metric, value):
    from metric_advisor import METRIC_THRESHOLDS
    t = METRIC_THRESHOLDS.get(metric)
    if t is None or value is None:
        return "GOOD"
    if t["direction"] == "higher_better":
        if value >= t["good"]: return "GOOD"
        if value >= t["warn"]: return "WARN"
        return "BAD"
    if value <= t["good"]: return "GOOD"
    if value <= t["warn"]: return "WARN"
    return "BAD"


# GitHub dark-theme contribution palette approximated in 256-color:
# L0 empty (#161b22) · L1 (#0e4429) · L2 (#006d32) · L3 (#26a641) · L4 (#39d353)
_CONTRIB_SHADES = [
    f"\033[38;5;{n}m" for n in (237, 22, 28, 34, 46)
]


def _weekly_contribution_row(daily, today_d):
    """7-day contribution strip: one block per day with weekday label and session count."""
    from datetime import timedelta as _td

    days = [today_d - _td(days=i) for i in range(6, -1, -1)]
    counts = [daily.get(d.isoformat(), {}).get("sessions", 0) for d in days]

    nonzero = sorted(c for c in counts if c > 0)
    if nonzero:
        n = len(nonzero)
        q1 = nonzero[n // 4]
        q2 = nonzero[n // 2]
        q3 = nonzero[(3 * n) // 4]
    else:
        q1 = q2 = q3 = 0

    def shade(c):
        if c <= 0: return 0
        if c <= q1: return 1
        if c <= q2: return 2
        if c <= q3: return 3
        return 4

    block_w = 4  # visual width of each day block
    gap = " "
    label_row = gap.join(f"{DIM}{d.strftime('%a'):^{block_w}}{RESET}" for d in days)
    block_row = gap.join(f"{_CONTRIB_SHADES[shade(c)]}{'█' * block_w}{RESET}" for c in counts)
    count_row = gap.join(
        f"{(BRIGHT_WHITE + BOLD) if c > 0 else DIM}{str(c):^{block_w}}{RESET}" for c in counts
    )
    pad = "  "
    return [pad + label_row, pad + block_row, pad + count_row]


def _contribution_matrix(store):
    """GitHub-style 52×7 heatmap of sessions-per-day over the last year."""
    from datetime import date, timedelta

    daily = store.get("daily", {})
    end = date.today()
    start = end - timedelta(days=52 * 7 - 1)
    # Snap start back to the nearest prior Sunday so columns align on week boundaries
    start = start - timedelta(days=(start.weekday() + 1) % 7)
    total_days = (end - start).days + 1
    cols = (total_days + 6) // 7

    # Build counts per date
    counts = {}
    for k, v in daily.items():
        try:
            d = date.fromisoformat(k)
        except Exception:
            continue
        if start <= d <= end:
            counts[d] = v.get("sessions", 0)

    # Compute shade thresholds from nonzero days (quartiles)
    nonzero = sorted(c for c in counts.values() if c > 0)
    if nonzero:
        n = len(nonzero)
        q1 = nonzero[n // 4]
        q2 = nonzero[n // 2]
        q3 = nonzero[(3 * n) // 4]
        qmax = nonzero[-1]
    else:
        q1 = q2 = q3 = qmax = 0

    def shade(c):
        if c <= 0: return 0
        if c <= q1: return 1
        if c <= q2: return 2
        if c <= q3: return 3
        return 4

    # rows[r] for r in 0..6 where 0=Sun, 6=Sat
    rows = [[] for _ in range(7)]
    for col in range(cols):
        for r in range(7):
            d = start + timedelta(days=col * 7 + r)
            if d > end:
                rows[r].append(None)
            else:
                rows[r].append(shade(counts.get(d, 0)))

    # Month label row: place 3-char month abbrev at the column where the month first appears
    month_slots = [""] * cols
    prev_month = None
    for col in range(cols):
        # Date at the top of the column (Sunday)
        d = start + timedelta(days=col * 7)
        if d.month != prev_month:
            month_slots[col] = d.strftime("%b")
            prev_month = d.month
    month_line_chars = [" "] * cols
    i = 0
    while i < cols:
        lbl = month_slots[i]
        if lbl and i + 3 <= cols:
            # Avoid stomping on the next label
            next_lbl_col = next((j for j in range(i + 1, min(i + 3, cols)) if month_slots[j]), None)
            if next_lbl_col is None:
                for k, ch in enumerate(lbl):
                    month_line_chars[i + k] = ch
                i += 3
                continue
        i += 1

    pad = "      "  # 6 spaces to match "  Mon " / "      " left gutter
    lines = []
    lines.append(pad + f"{DIM}" + "".join(month_line_chars) + f"{RESET}")

    # Only "Mon", "Wed", "Fri" labels are shown (GitHub convention); other rows blank.
    day_labels = ["   ", "Mon", "   ", "Wed", "   ", "Fri", "   "]
    # Batch ANSI colour codes per run of same-shade cells instead of per cell.
    # Output otherwise grows to ~6KB of escape codes alone, which pushes the
    # overall hook stdout past Claude Code's ~13KB truncation threshold.
    for r in range(7):
        label = day_labels[r]
        parts = []
        cur_shade = None
        run = ""
        def flush():
            nonlocal parts, cur_shade, run
            if run:
                if cur_shade is None:
                    parts.append(run)
                else:
                    parts.append(f"{_CONTRIB_SHADES[cur_shade]}{run}{RESET}")
            run = ""
            cur_shade = None
        for v in rows[r]:
            if v is None:
                if cur_shade is not None:
                    flush()
                run += " "
            else:
                if cur_shade != v:
                    flush()
                    cur_shade = v
                run += "■"
        flush()
        lines.append(f"  {DIM}{label}{RESET} " + "".join(parts))

    # Legend + summary
    active_days = sum(1 for c in counts.values() if c > 0)
    total_sessions = sum(counts.values())
    legend = "".join(f"{_CONTRIB_SHADES[i]}■{RESET}" for i in range(5))
    lines.append("")
    lines.append(
        f"  {DIM}less{RESET} {legend} {DIM}more{RESET}   "
        f"{BRIGHT_WHITE}{BOLD}{total_sessions}{RESET}{DIM} sessions across {RESET}"
        f"{BRIGHT_WHITE}{BOLD}{active_days}{RESET}{DIM} days this year{RESET}"
    )
    return lines


def print_insights(store, yesterday_str):
    """Editorial-style metrics dashboard with sparklines and severity gauges."""
    from metric_advisor import compute_deltas, evaluate_metrics, METRIC_THRESHOLDS, \
        load_analysis_history, save_analysis_history

    cum = store.get("cumulative", {})
    projects = store.get("by_project", {})
    pc = cum.get("prompt_classifications", {})

    # Find the most recent active day — falls back gracefully when yesterday is empty
    daily = store.get("daily", {})
    sorted_days = sorted(daily.keys(), reverse=True)
    active_day_key = yesterday_str if yesterday_str in daily else (sorted_days[0] if sorted_days else None)
    active = daily.get(active_day_key) if active_day_key else None

    # Leading blank line so the dashboard separates visually from whatever
    # Claude Code's UI prints above it (welcome banner, prior hook output, etc.).
    out = [""]

    # ── Header: minimal editorial mark ─────────────────────────────────────────
    today_str = datetime.now().strftime('%a %b %d')
    left = f"{BRIGHT_CYAN}{BOLD}{' '.join('RETRO')}{RESET}  {DIM}·{RESET}  {BRIGHT_CYAN}{' '.join('DAILY')}{RESET}"
    right = f"{DIM}{today_str}{RESET}"
    left_w = _visible_len(left)
    right_w = _visible_len(right)
    gap = max(2, _RULE_WIDTH - left_w - right_w)
    out.append(left + (' ' * gap) + right)
    out.append(f"{BRIGHT_CYAN}{'━' * _RULE_WIDTH}{RESET}")
    out.append("")

    # ── All-time ──────────────────────────────────────────────────────────────
    out.append(_section("ALL-TIME"))
    cost = cum.get("total_estimated_cost", 0)
    cost_part = f"   {BRIGHT_GREEN}${cost:.2f}{DIM} est.{RESET}" if cost else ""
    out.append(
        f"  {BRIGHT_WHITE}{BOLD}{cum.get('total_sessions', 0):>5}{RESET} {DIM}sessions{RESET}  "
        f"{BRIGHT_WHITE}{BOLD}{cum.get('total_tools', 0):>5}{RESET} {DIM}tools{RESET}  "
        f"{BRIGHT_WHITE}{BOLD}{cum.get('active_days', 0):>3}{RESET} {DIM}days{RESET}  "
        f"{BRIGHT_WHITE}{BOLD}{len(projects):>3}{RESET} {DIM}projects{RESET}"
        f"{cost_part}"
    )
    if cost:
        if PLAN_LABEL:
            out.append(f"  {DIM}API-equivalent value · actual out-of-pocket capped by {PLAN_LABEL}{RESET}")
        else:
            out.append(f"  {DIM}API-equivalent estimate · not your actual bill if on a Claude subscription{RESET}")
    tt = cum.get("total_tokens", {})
    if tt and (tt.get("input") or tt.get("output")):
        def _fmt(n):
            if n >= 1e9: return f"{n/1e9:.2f}B"
            if n >= 1e6: return f"{n/1e6:.1f}M"
            if n >= 1e3: return f"{n/1e3:.1f}K"
            return str(n)
        out.append(
            f"  {DIM}tokens{RESET}  "
            f"{BRIGHT_WHITE}{_fmt(tt.get('input',0))}{RESET} {DIM}in{RESET}  "
            f"{BRIGHT_WHITE}{_fmt(tt.get('output',0))}{RESET} {DIM}out{RESET}  "
            f"{BRIGHT_WHITE}{_fmt(tt.get('cache_read',0))}{RESET} {DIM}cache-read{RESET}  "
            f"{BRIGHT_WHITE}{_fmt(tt.get('cache_create',0))}{RESET} {DIM}cache-write{RESET}"
        )
    out.append("")

    # ── Last 7 days ──────────────────────────────────────────────────────────
    from datetime import date as _date, timedelta as _td
    today_d = _date.today()
    week_keys = [(today_d - _td(days=i)).isoformat() for i in range(7)]
    wk_days = [daily[k] for k in week_keys if k in daily]
    if wk_days:
        wk_sessions = sum(d.get("sessions", 0) for d in wk_days)
        wk_tools = sum(d.get("total_tools", 0) for d in wk_days)
        wk_active = sum(1 for d in wk_days if d.get("sessions", 0) > 0)
        wk_projects = set()
        for d in wk_days:
            wk_projects.update(d.get("projects", []))
        wk_cost = sum(d.get("estimated_cost", 0) for d in wk_days)
        wk_cost_part = f"   {BRIGHT_GREEN}${wk_cost:.2f}{DIM} est.{RESET}" if wk_cost else ""
        out.append(_section("LAST 7 DAYS"))
        out.append(
            f"  {BRIGHT_WHITE}{BOLD}{wk_sessions:>5}{RESET} {DIM}sessions{RESET}  "
            f"{BRIGHT_WHITE}{BOLD}{wk_tools:>5}{RESET} {DIM}tools{RESET}  "
            f"{BRIGHT_WHITE}{BOLD}{wk_active:>3}{RESET} {DIM}days{RESET}  "
            f"{BRIGHT_WHITE}{BOLD}{len(wk_projects):>3}{RESET} {DIM}projects{RESET}"
            f"{wk_cost_part}"
        )
        # Compare against prior-7-days window for a delta line
        prev_keys = [(today_d - _td(days=i)).isoformat() for i in range(7, 14)]
        prev_days = [daily[k] for k in prev_keys if k in daily]
        if prev_days:
            prev_sessions = sum(d.get("sessions", 0) for d in prev_days)
            prev_tools = sum(d.get("total_tools", 0) for d in prev_days)
            prev_cost = sum(d.get("estimated_cost", 0) for d in prev_days)

            def _delta(curr, prev, is_money=False):
                if prev == 0:
                    return f"{DIM}—{RESET}"
                pct = (curr - prev) / prev * 100
                arrow = "↑" if pct >= 0 else "↓"
                color = BRIGHT_GREEN if pct >= 0 else BRIGHT_RED
                return f"{color}{arrow}{abs(pct):.0f}%{RESET}"

            out.append(
                f"  {DIM}vs prior 7d{RESET}  "
                f"sessions {_delta(wk_sessions, prev_sessions)}  "
                f"tools {_delta(wk_tools, prev_tools)}  "
                f"cost {_delta(wk_cost, prev_cost, True)}"
            )
        out.append("")
        out.extend(_weekly_contribution_row(daily, today_d))
        out.append("")

    # ── Competency: composite score + letter grade ───────────────────────────
    scores = []
    for m in ["edit_read_ratio", "auto_rate", "first_try_rate", "correction_rate", "tool_error_rate", "ctx_compact_rate"]:
        v = cum.get(m)
        s = _metric_score(m, v)
        if s is not None:
            scores.append(s)
    if scores:
        composite = sum(scores) / len(scores)
        grade = _letter_grade(composite)
        gcolor = _grade_color(composite)
        # Wide gauge (30 cells) for the composite score — visual weight matches its importance
        width = 30
        filled = int(round(composite / 100 * width))
        bar_color = (BRIGHT_GREEN if composite >= 80
                     else BRIGHT_CYAN if composite >= 70
                     else BRIGHT_YELLOW if composite >= 60
                     else BRIGHT_RED)
        out.append(_section("COMPETENCY"))
        out.append(
            f"  {bar_color}{'█' * filled}{DIM}{'░' * (width - filled)}{RESET}  "
            f"{BRIGHT_WHITE}{BOLD}{composite:5.1f}{RESET}{DIM}/100{RESET}   "
            f"{gcolor}{grade:>2}{RESET}"
        )
        breakdown = []
        for m, s in zip(["edit_read_ratio", "auto_rate", "first_try_rate", "correction_rate", "tool_error_rate", "ctx_compact_rate"], scores):
            label = METRIC_DISPLAY.get(m, m).replace(" / ", "/")
            sev = _severity_for(m, cum.get(m))
            scolor = _severity_color(sev)
            breakdown.append(f"{DIM}{label}{RESET} {scolor}{int(round(s))}{RESET}")
        out.append(f"  {DIM}breakdown   {RESET}{'  '.join(breakdown)}")
        out.append("")

    # ── Efficiency grid with sparklines + severity dots ───────────────────────
    out.append(_section("EFFICIENCY"))
    deltas = compute_deltas(store)
    # Column header
    out.append(
        f"  {DIM}{_pad('metric', 14)}  {_pad('value', 7, 'right')}   "
        f"{_pad('14-day trend', 14)}   {_pad('7d', 3)}  {_pad('30d', 3)}   status{RESET}"
    )
    for metric in ["edit_read_ratio", "auto_rate", "first_try_rate", "correction_rate", "tool_error_rate", "ctx_compact_rate"]:
        label = METRIC_DISPLAY.get(metric, metric)
        suffix = METRIC_SUFFIX.get(metric, "")
        value = cum.get(metric)
        if value is None and metric in deltas:
            value = deltas[metric].get("value")
        if value is None:
            value = 0
        severity = _severity_for(metric, value)
        direction = METRIC_THRESHOLDS.get(metric, {}).get("direction", "higher_better")
        hist = _metric_history(store, metric, window=14)
        spark = _spark(hist, width=14)
        d7 = deltas.get(metric, {}).get("7d")
        d30 = deltas.get(metric, {}).get("30d")
        a7 = _trend_arrow(d7, direction)
        a30 = _trend_arrow(d30, direction)
        value_str = f"{value}{suffix}"
        sev_col = _severity_color(severity)
        out.append(
            f"  {_pad(label, 14)}  "
            f"{_pad(BRIGHT_WHITE + BOLD + value_str + RESET, 7, 'right')}   "
            f"{spark}   "
            f"{_pad(a7, 3)}  {_pad(a30, 3)}   "
            f"{_severity_dot(severity)} {DIM}{sev_col}{severity.lower()}{RESET}"
        )

    # Prompt breakdown
    if pc:
        out.append("")
        total = sum(pc.values()) or 1
        out.append(
            f"  {DIM}prompts:{RESET} "
            f"{BRIGHT_GREEN}{pc.get('APPROVAL',0)}{RESET}{DIM} approved · {RESET}"
            f"{BRIGHT_CYAN}{pc.get('NEW_TASK',0)}{RESET}{DIM} new · {RESET}"
            f"{BRIGHT_YELLOW}{pc.get('REFINEMENT',0)}{RESET}{DIM} refined · {RESET}"
            f"{BRIGHT_MAGENTA}{pc.get('CORRECTION',0)}{RESET}{DIM} corrected{RESET}"
        )
    out.append("")

    # ── Contribution heatmap (52×7) ──────────────────────────────────────────
    out.append(_section("CONTRIBUTIONS"))
    out.extend(_contribution_matrix(store))
    out.append("")

    # ── Last active day ──────────────────────────────────────────────────────
    if active and active_day_key:
        try:
            pretty = datetime.strptime(active_day_key, "%Y-%m-%d").strftime("%a %b %d")
        except Exception:
            pretty = active_day_key
        header_label = "YESTERDAY" if active_day_key == yesterday_str else f"LAST ACTIVE · {pretty.upper()}"
        out.append(_section(header_label))
        projs = ", ".join(active.get("projects", []))
        day_cost = active.get("estimated_cost", 0)
        cost_part = f"  {BRIGHT_GREEN}${day_cost:.2f}{DIM} est.{RESET}" if day_cost else ""
        out.append(
            f"  {BRIGHT_WHITE}{BOLD}{active['sessions']:>3}{RESET} {DIM}sessions{RESET}  "
            f"{BRIGHT_WHITE}{BOLD}{active['total_tools']:>4}{RESET} {DIM}tools{RESET}"
            f"{cost_part}  {DIM}[{projs}]{RESET}"
        )

        topics = active.get("topics", {})
        if topics:
            topic_parts = [f"{BRIGHT_CYAN}{t}{RESET}{DIM}·{c}{RESET}" for t, c in sorted(topics.items(), key=lambda x: -x[1])]
            out.append(f"  {DIM}topics   {RESET}{' '.join(topic_parts)}")

        itypes = active.get("interaction_types", {})
        if itypes:
            itype_parts = [f"{BRIGHT_BLUE}{t}{RESET}{DIM}·{c}{RESET}" for t, c in sorted(itypes.items(), key=lambda x: -x[1])]
            out.append(f"  {DIM}work     {RESET}{' '.join(itype_parts)}")

        branches = active.get("branches", [])
        if branches:
            out.append(f"  {DIM}branches {', '.join(branches[:5])}{RESET}")

        summaries = active.get("session_summaries", [])
        if summaries:
            out.append("")
            for s in summaries[:3]:
                out.append(f"  {DIM}›{RESET} {DIM}\"{s}\"{RESET}")

        terr = active.get("tool_errors", 0)
        if terr > 0:
            terr_rate = active.get("tool_error_rate", 0)
            err_types = active.get("tool_error_types", {})
            err_parts = [f"{t}({c})" for t, c in sorted(err_types.items(), key=lambda x: -x[1]) if c > 0]
            out.append(f"  {BRIGHT_RED}✗{RESET} {terr} tool errors ({terr_rate}%) — {DIM}{', '.join(err_parts)}{RESET}")
    else:
        out.append(_section("RECENT"))
        out.append(f"  {DIM}No session data yet.{RESET}")
    out.append("")

    # ── Weak metrics with severity gauges ────────────────────────────────────
    recent_topics = list(active.get("topics", {}).keys()) if active else []
    weak = evaluate_metrics(store, topics=recent_topics)
    if weak:
        out.append(_section("FOCUS AREAS"))
        scout_queries = []
        weak_names = []
        for w in weak:
            sev = w['severity']
            metric = w['metric']
            label = METRIC_DISPLAY.get(metric, metric)
            suffix = METRIC_SUFFIX.get(metric, "")
            t = METRIC_THRESHOLDS.get(metric, {})
            gauge = _gauge(
                w['value'], t.get("warn", 0), t.get("good", 0),
                t.get("direction", "higher_better"),
                width=18, severity=sev,
            )
            sev_col = _severity_color(sev)
            topic_marker = f" {DIM}(topic-specific){RESET}" if w.get("is_topic_specific") else ""
            out.append(
                f"  {_severity_dot(sev)} {sev_col}{BOLD}{sev:<4}{RESET} "
                f"{_pad(label, 13)} {gauge} "
                f"{BRIGHT_WHITE}{BOLD}{w['value']}{suffix}{RESET}   "
                f"{DIM}warn {t.get('warn','?')}{suffix} · good {t.get('good','?')}{suffix}{RESET}"
            )
            out.append(f"      {DIM}→{RESET} {w['recommendation']}{topic_marker}")
            scout_queries.extend(w.get("search_queries", []))
            weak_names.append(metric)

        # Analysis history — dedupe on (date, metrics)
        history = load_analysis_history()
        history["last_analysis"] = yesterday_str
        new_entry = {"date": yesterday_str, "metrics": sorted(weak_names)}
        wmh = history.get("weak_metrics_history", [])
        seen = {(e.get("date"), tuple(sorted(e.get("metrics", [])))) for e in wmh}
        key = (new_entry["date"], tuple(new_entry["metrics"]))
        if key not in seen:
            wmh.append(new_entry)
        history["weak_metrics_history"] = wmh[-30:]
        save_analysis_history(history)

        if scout_queries:
            out.append("")
            last_scout = history.get("last_scout") or "never"
            out.append(f"  {DIM}scout queued · last run {last_scout}{RESET}")

            scout_data = {
                "queries": list(dict.fromkeys(scout_queries))[:6],
                "weak_metrics": sorted(weak_names),
                "date": yesterday_str,
            }
            scout_path = METRICS_DIR / "scout-queries.json"
            with open(scout_path, "w") as f:
                json.dump(scout_data, f, indent=2)

    # Tag freshness signal: if last tagging run is stale, surface a hint.
    try:
        history_path = DATA_DIR / "analysis-history.json"
        if history_path.exists():
            from datetime import date as _date
            history = json.load(open(history_path))
            last_tag = history.get("last_session_tagging")
            if last_tag:
                from datetime import date as _d, timedelta as _td
                days = (_d.today() - _d.fromisoformat(last_tag)).days
                if days >= 14:
                    out.append("")
                    out.append(f"  {BRIGHT_YELLOW}●{RESET} session tags last refreshed {days} days ago — "
                               f"{DIM}new sessions show as 'untagged' until next weekly run{RESET}")
    except Exception:
        pass

    out.append("")
    out.append(f"{DIM}{'─' * _RULE_WIDTH}{RESET}")

    output = "\n".join(out)
    print(output)


if __name__ == "__main__":
    main()
