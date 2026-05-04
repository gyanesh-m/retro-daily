```
   ▄████▄   ██▓    ▄▄▄       █    ██ ▓█████▄ ▓█████
  ▒██▀ ▀█  ▓██▒   ▒████▄     ██  ▓██▒▒██▀ ██▌▓█   ▀
  ▒▓█    ▄ ▒██░   ▒██  ▀█▄  ▓██  ▒██░░██   █▌▒███
  ▒▓▓▄ ▄██▒▒██░   ░██▄▄▄▄██ ▓▓█  ░██░░▓█▄   ▌▒▓█  ▄
  ▒ ▓███▀ ░░██████▒▓█   ▓██▒▒▒█████▓ ░▒████▓ ░▒████▒
  ░ ░▒ ▒  ░░ ▒░▓  ░▒▒   ▓▒█░░▒▓▒ ▒ ▒  ▒▒▓  ▒ ░░ ▒░ ░
    ░  ▒   ░ ░ ▒  ░ ▒   ▒▒ ░░░▒░ ░ ░  ░ ▒  ▒  ░ ░  ░
  ░          ░ ░    ░   ▒    ░░░ ░ ░  ░ ░  ░    ░
  ░ ░          ░  ░     ░  ░   ░        ░       ░  ░

           D · A · I · L · Y    [v0.1]
       ════════════════════════════════════
        retro analytics for claude code
```

A daily dashboard for your Claude Code sessions. Renders at the top of every session via a `SessionStart` hook — sessions, tools, cost, competency grade, efficiency trends, contributions heatmap, and a self-updating "scout" that searches docs and GitHub for ideas tied to your weakest metrics.

## Sample output

```
C L A U D E  ·  D A I L Y                                 Mon May 04
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A L L - T I M E
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   1197 sessions  10626 tools   21 days   15 projects   $6436.49 est.
  tokens  239.0K in  10.6M out  1.82B cache-read  127.2M cache-write

C O M P E T E N C Y
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ███████████████████░░░░░░░░░░░   62.1/100    D
  breakdown   Edit/Read 100  Auto-approve 29  First-try 100  ...

E F F I C I E N C Y
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  metric            value   14-day trend     7d   30d   status
  Edit / Read         1.0   ▄▂▁▃▂▃▂▅▄█▄█▄▁   ↓    ↓     ⬤ good
  Auto-approve      65.7%   ▇▆▁▇▃▆▆▄▆█▇██▂   ↓    ↓     ⬤ bad
  First-try         83.4%   ▇██▇▇███▇▇█▇█▁   ↓    ↓     ⬤ good
  Corrections       15.1%   ▇▄▃▄█▂▁▂▁▁▃▁▁▁   ↓    ↓     ⬤ bad
  Tool errors       10.2%   ▂▄▅▁▃▂▂▂▃█▃█▃▁   ↓    ↓     ⬤ bad
  Ctx hygiene       50.0%   ·········▁▁▁██   ↓    ↓     ⬤ warn

C O N T R I B U T I O N S
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      May Jun  Jul Aug  Sep Oct Nov  Dec Jan Feb Mar  Apr
     ■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
  Mon ■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
  ...
  less ■■■■■ more   1197 sessions across 21 days this year

S C O U T   F I N D I N G S
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ● claude code auto approve setup
      → If on Team plan, run `claude --permission-mode auto` ...
      ★ oryband/claude-code-auto-approve · Install as a PreToolUse hook ...
```

## Install

> Pick **one** of the two methods. Running both registers the hook twice.

### Option A — Claude Code plugin (recommended)

Inside Claude Code:

```
/plugin marketplace add gyanesh-m/claude-daily
/plugin install claude-daily@claude-daily
/reload-plugins
```

The repo doubles as its own single-plugin marketplace. State lives under `${CLAUDE_PLUGIN_DATA}` (`~/.claude/plugins/data/claude-daily-claude-daily/`) so plugin updates and uninstalls clean up after themselves.

Test against a local clone before publishing:

```sh
claude --plugin-dir ./claude-daily
```

### Option B — standalone script

```sh
git clone https://github.com/gyanesh-m/claude-daily.git
cd claude-daily && ./install.sh
```

Copies scripts to `~/.claude/metrics/`, marks them executable, and merges a `SessionStart` hook into `~/.claude/settings.json` via `jq` (idempotent; falls back to printing the JSON to paste manually if `jq` is missing).

Open a new Claude Code session — the dashboard renders.

## Paths

The scripts resolve their layout from two env vars. Defaults preserve the legacy single-directory layout for standalone installs; the plugin's `hooks.json` overrides both for plugin installs.

| Env var | Standalone default | Plugin default |
|---|---|---|
| `CLAUDE_DAILY_HOME` | script's own directory | `${CLAUDE_PLUGIN_ROOT}` |
| `CLAUDE_DAILY_DATA` | `~/.claude/metrics` | `${CLAUDE_PLUGIN_DATA}` |
| `CLAUDE_DAILY_PLAN_LABEL` | unset → generic footer | unset → generic footer |

Set `CLAUDE_DAILY_PLAN_LABEL="Claude Max $100/mo"` (or `"Claude Pro $20/mo"`, `"API"`, etc.) if you want the cost footer to name your plan. Claude Code does not expose the active subscription tier programmatically, so this can't be auto-detected.

## Requirements

- `python3` (3.9+) — required
- `claude` CLI on `$PATH` — required for the scout background worker
- `jq` — only for the standalone installer's `settings.json` merge

### Python dependencies

The prompt classifier uses `sentence-transformers` (~90MB MiniLM, required for topic similarity) and optionally `transformers` + `sentencepiece` (~500MB DeBERTa NLI, fallback for reactions that don't match any lexical cue). On the synthetic eval, lexical cues alone classify 49/50 cases correctly — NLI is insurance, not the primary path.

These are installed into a venv at `${CLAUDE_DAILY_DATA}/.venv` so they don't pollute system Python.

**Standalone install** runs `setup-venv.sh` automatically — first run downloads ~600MB of model deps.

**Plugin install** does not auto-bootstrap (plugin install paths are read-only at install time). After `/plugin install`, run once:

```sh
bash ~/.claude/plugins/cache/<marketplace>/<plugin>/setup-venv.sh
```

Or, simpler — clone and run:

```sh
git clone https://github.com/gyanesh-m/claude-daily.git
CLAUDE_DAILY_DATA=~/.claude/plugins/data/claude-daily-claude-daily \
  bash ./claude-daily/setup-venv.sh
```

The dashboard renders even without the venv — only the embedding-driven prompt outcome classification (APPROVAL / REFINEMENT / CORRECTION) is skipped.

## How classification works

| Signal | Source | Cadence |
|---|---|---|
| Prompt outcome (APPROVAL / REFINEMENT / CORRECTION / NEW_TASK) | `prompt_classifier.py` — lexical cues + zero-shot NLI fallback | Every regen (once per day) |
| Topic + interaction type per session | `tag-sessions-runner.sh` — `claude -p` labels each session with a free-form noun phrase | Once per week |
| Extractive summary of representative messages | `session_enricher.py` — longest-unique heuristic | Every regen |

The prompt classifier hits 98% on `tests/eval.json` (a 50-pair synthetic dataset). Run `python3 tests/eval_classifier.py` to verify against your own labels.

Session tags are surfaced as the `topics` and `interaction_types` fields per day in `metrics-store.json`. Untagged sessions (newly created since the last weekly run) show as `untagged` until the next tagging cycle.

## Files

| File | Role |
|---|---|
| `startup.sh` | hook entrypoint, runs the steps below |
| `daily-insights.sh` + `generate-metrics.py` + `metric_advisor.py` | dashboard renderer |
| `prompt_classifier.py` | hybrid cue + zero-shot NLI prompt classifier |
| `session_enricher.py` | session tag loader + extractive summary |
| `scout.sh` + `scout-runner.sh` + `scout-review.sh` + `scout-browse.sh` | background scout worker for weak-metric guidance |
| `tag-sessions.sh` + `tag-sessions-runner.sh` | weekly LLM session tagger |
| `tests/eval.json` + `tests/eval_classifier.py` + `tests/sample_pairs.py` | classifier regression test |
| `_paths.sh` | shared `CLAUDE_DAILY_HOME` / `CLAUDE_DAILY_DATA` resolution |
| `install.sh` + `setup-venv.sh` + `requirements.txt` | standalone installer + Python venv bootstrap |
| `.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json` + `hooks/hooks.json` | plugin packaging |

## Uninstall

**Plugin install:**

```
/plugin uninstall claude-daily@claude-daily
```

This also clears `~/.claude/plugins/data/claude-daily-claude-daily/`. Pass `--keep-data` to preserve the metrics store across reinstalls.

**Standalone install:**

```sh
rm -rf ~/.claude/metrics
```

Then remove the `SessionStart` hook entry from `~/.claude/settings.json`.

```
                  [ press any key to continue ]
```
