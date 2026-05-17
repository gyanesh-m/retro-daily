# tests/

Tiny eval harness for the prompt classifier.

## What's here

| File | Role |
|---|---|
| `eval.json` | 50 hand-crafted (prompt, reaction, label) triples shipped with the repo. **Synthetic** — not drawn from any user's session history — so the public dataset is privacy-safe and reproducible. Covers all four classes (APPROVAL / REFINEMENT / CORRECTION / NEW_TASK). |
| `eval_classifier.py` | Loads the dataset, runs the current classifier, prints overall accuracy + a confusion matrix + per-class precision/recall/F1. Optional `--min` flag turns it into a regression gate. |
| `sample_pairs.py` | Bootstraps a **private** eval set from your own `~/.claude/projects/*.jsonl` history. Output is gitignored — never commit it. |

## Run the public eval

```sh
# After standalone install, from the repo root:
~/.claude/metrics/.venv/bin/python3 tests/eval_classifier.py
# Or activate the venv and run plain python3.
```

Add `--min 0.80` to fail with exit code 1 if accuracy drops below 80%. Use this in CI or as a pre-push hook.

## Build your own private eval

```sh
python3 tests/sample_pairs.py --n 80 --since 30
# Edit tests/eval.local-unlabeled.json: replace each "?" with one of
#   APPROVAL | REFINEMENT | CORRECTION | NEW_TASK
# Save as tests/eval.local.json (gitignored).
python3 tests/eval_classifier.py --eval tests/eval.local.json
```

50 labeled pairs is the rough floor for stable accuracy estimates — below that, single mistakes move the number by 2%+.

## Caveats

- One author's labels reflect one author's intuitions. Treat the synthetic `eval.json` as a smoke test, not a benchmark.
- The 4-class taxonomy collapses real ambiguity ("almost good but also new question" maps to *something*). Don't chase the last 5% of accuracy — chase whether the rates printed in the dashboard line up with how you actually felt about the day.
- This harness only tests the prompt classifier. Topic and interaction-type classifications (in `session_enricher.py`) are LLM-driven after Phase C and don't have a numeric eval — review the labels in `session-tags.json` directly if they look off.
