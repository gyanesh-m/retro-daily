# Claude Code Daily Analytics

Automated metrics collection and insight generation for all Claude Code sessions. Runs once per day via a `SessionStart` hook, processes yesterday's sessions, and surfaces key insights at the start of your first session each day.

## How It Works

```
You open Claude Code
  → SessionStart hook fires
  → daily-insights.sh checks last-run-date.txt
  → Already ran today? Exit in 22ms. Done.
  → New day? Run generate-metrics.py:
      1. Scan all project dirs under ~/.claude/projects/
      2. Find JSONL session logs from unprocessed dates (up to yesterday)
      3. Extract tool usage, permission waits, user messages
      4. Run embedding classifier on user message pairs
      5. Append daily metrics to metrics-store.json
      6. Print insights to transcript
      7. Write today's date to last-run-date.txt
  → Next session today: skip (22ms)
```

## What It Measures

### Tool Efficiency
| Metric | What | Good |
|--------|------|------|
| Edit/Read ratio | Edits+Writes ÷ Reads+Greps+Globs | >1.0 (modifying, not just browsing) |
| Tools per user message | Total tool calls ÷ user messages | <1.5 (batching, parallelism) |
| Agent delegation rate | Agent calls as % of all tools | 3–15% (delegation without over-spawning) |
| Bash usage | Bash calls as % of all tools | <25% (prefer dedicated tools) |

### Permission Interrupts
| Metric | What | Good |
|--------|------|------|
| Auto-approve rate | Tool calls approved without prompting | >75% (trust is calibrated) |
| Median wait | Time user takes to approve/deny | <15s (fast feedback loop) |
| p90 wait | 90th percentile approval wait | <120s (outliers under control) |
| Denial rate | Tool calls explicitly denied | <2% (Claude is well-behaved) |

### Prompt Effectiveness (Embedding-Based)

Uses `all-MiniLM-L6-v2` (sentence-transformers) to classify consecutive user message pairs. For each `(prompt[i], prompt[i+1])` pair, the classifier determines what the user's reaction means:

| Classification | Meaning | Counts as success? |
|---------------|---------|-------------------|
| **APPROVAL** | User accepted — "lgtm", "perfect", "ship it" | Yes |
| **NEW_TASK** | User moved to unrelated topic (prompt worked, done) | Yes |
| **REFINEMENT** | Minor tweak — "also add", "make it more" | No (but not failure) |
| **CORRECTION** | Wrong direction — "no", "undo", "that's not what I meant" | No |

| Metric | What | Good |
|--------|------|------|
| First-try rate | (APPROVAL + NEW_TASK) ÷ total pairs × 100 | >65% |
| Correction count | Actual course corrections per day | Trending down |

**How the classifier works:**
1. Pre-computes category centroids from ~20 reference phrases each
2. Embeds all user messages in a session as a batch (fast)
3. Each reaction is compared against category centroids via cosine similarity
4. Topic similarity between consecutive messages helps distinguish NEW_TASK (low sim) from CORRECTION (high sim, negative sentiment)

**Why MiniLM, not regex:**
- Regex catches "no, don't" but misses "hmm, I was thinking more like..."
- Regex false-positives on brainstorming ("no, something else" = exploring, not correcting)
- Embeddings understand semantic intent, not just keyword presence
- MiniLM is 80MB, runs in <50ms per embed on CPU, no API costs

## Files

```
~/.claude/metrics/
├── README.md                 # This file
├── generate-metrics.py       # Main generator — processes JSONLs, runs classifier
├── prompt_classifier.py      # Embedding-based prompt effectiveness classifier
├── daily-insights.sh         # Hook wrapper — date-gate, runs generator if needed
├── .venv/                    # Isolated Python env (sentence-transformers, torch)
├── metrics-store.json        # Persistent daily metrics store (auto-generated)
└── last-run-date.txt         # Date of last successful run (auto-generated)
```

## Hook Configuration

The hook is registered globally in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/metrics/daily-insights.sh",
            "timeout": 30,
            "statusMessage": "Checking daily analytics..."
          }
        ]
      }
    ]
  }
}
```

This fires on every session start, for every project. The bash script handles the once-per-day gate internally.

## Sample Output

On the first session of a new day:

```
Daily Analytics Summary
All-time: 62 sessions | 1681 tools | 7 active days | 9 projects
Efficiency: Edit/Read 1.2 | Auto-approve 78.7% | First-try rate 66.2%
Prompt breakdown: 155 approvals, 305 new tasks, 59 refinements, 176 corrections

Yesterday (2026-04-05): 1 session, 666 tools, first-try 72.3% [rephrase-kit-repo]
  Prompts: 50 approved, 30 new tasks, 8 refinements, 12 corrections
```

Warnings surface automatically:
```
  Warning: More corrections than approvals. Check prompt clarity.
  Warning: Low first-try rate. Many prompts needed follow-up corrections.
  Warning: Slow permission waits. Consider expanding auto-approve rules.
```

## Performance

| Scenario | Time |
|----------|------|
| Fast path (already ran today) | 22ms |
| Full run (model cached, few sessions) | <1s |
| Full run (model cold load, many sessions) | ~15s |
| Full run (first ever, downloads model) | ~60s |

The MiniLM model (~80MB) downloads once on first run and is cached at `~/.cache/torch/sentence_transformers/`.

## Data Flow

```
~/.claude/projects/*/     JSONL session logs (source of truth)
        │
        ▼
generate-metrics.py       Processes unprocessed dates
        │
        ├──► prompt_classifier.py    Embeds user messages, classifies pairs
        │
        ▼
metrics-store.json        Persistent store (daily + cumulative + per-project)
        │
        ▼
stdout (hook output)      Key insights shown in Claude Code transcript
```

## Manually Running

```bash
# Force a fresh run (reprocesses all dates)
rm ~/.claude/metrics/last-run-date.txt ~/.claude/metrics/metrics-store.json
~/.claude/metrics/.venv/bin/python3 ~/.claude/metrics/generate-metrics.py

# Check stored metrics
cat ~/.claude/metrics/metrics-store.json | python3 -m json.tool

# Run classifier on a single session interactively
~/.claude/metrics/.venv/bin/python3 -c "
from prompt_classifier import PromptClassifier
c = PromptClassifier()
result = c.classify_pair('add a login page', 'no, I meant a signup page')
print(result)  # {'category': 'CORRECTION', 'confidence': 0.612, 'topic_sim': 0.847}
"
```

## Extending

**Add new reference phrases** to `prompt_classifier.py` `REFERENCE_PHRASES` dict to improve classification accuracy for your patterns.

**Add new metrics** to `process_session()` in `generate-metrics.py` — any data extractable from the JSONL messages is fair game.

**Dashboard** — run `open /tmp/claude-analytics.html` for the full interactive Chart.js dashboard (generated separately, not part of the daily hook).

## Dependencies

- Python 3.9+
- sentence-transformers (installed in .venv)
- torch (pulled by sentence-transformers)
- numpy (pulled by sentence-transformers)

All dependencies are isolated in `.venv/` — no global pip installs.
