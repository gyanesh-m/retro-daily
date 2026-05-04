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

A daily dashboard for your Claude Code sessions. Renders at the top of every session via a `SessionStart` hook — sessions, tools, cost, competency grade, efficiency trends, and a self-updating "scout" that searches docs and GitHub for ideas tied to your weakest metrics.

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

### Option A — Claude Code plugin (recommended)

Inside Claude Code:

```
/plugin marketplace add gyanesh-m/claude-daily
/plugin install claude-daily@claude-daily
```

The repo ships its own marketplace (`.claude-plugin/marketplace.json`), plugin manifest (`.claude-plugin/plugin.json`), and `hooks/hooks.json`. After install, run `/reload-plugins` and the `SessionStart` hook registers automatically. Plugin state lives in `${CLAUDE_PLUGIN_DATA}` (`~/.claude/plugins/data/claude-daily-claude-daily/`).

### Option B — standalone script

```sh
git clone https://github.com/gyanesh-m/claude-daily.git
cd claude-daily && ./install.sh
```

Copies scripts to `~/.claude/metrics/`, marks them executable, and merges a `SessionStart` hook into `~/.claude/settings.json` (creates the file if missing).

Open a new Claude Code session — the dashboard renders.

### Paths

| Env var | Default | What |
|---|---|---|
| `CLAUDE_DAILY_HOME` | script's own directory | code (read-only) |
| `CLAUDE_DAILY_DATA` | `~/.claude/metrics` | state: store, results, logs, archive, cached venv |

## Requirements

- `python3` with `numpy` and `sentence-transformers` (for the embedding-based prompt classifier)
- `jq` (for the installer's settings.json merge)
- `claude` CLI (for the scout background worker)

## Files

| File | Role |
|---|---|
| `startup.sh` | hook entrypoint |
| `daily-insights.sh` | dashboard driver |
| `generate-metrics.py` | renderer + metric computation |
| `metric_advisor.py` | thresholds, deltas, severity |
| `prompt_classifier.py` | embedding-based prompt outcome classification |
| `session_enricher.py` | per-session enrichment + topic extraction |
| `scout.sh` / `scout-runner.sh` | background scout worker |
| `scout-review.sh` | renders the SCOUT FINDINGS block |
| `scout-browse.sh` | interactive viewer for archived findings |

## Uninstall

```sh
rm -rf ~/.claude/metrics
# then remove the SessionStart hook entry from ~/.claude/settings.json
```

```
                  [ press any key to continue ]
```
