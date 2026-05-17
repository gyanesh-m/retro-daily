#!/usr/bin/env python3
"""
Regression test for the prompt classifier.

Loads tests/eval.json (a fixed labeled dataset of (prompt, reaction, label)
triples), runs the current classifier over each pair, and prints overall
accuracy plus a confusion matrix. Exits non-zero if accuracy falls below the
floor declared on the command line (default 0.0 = report only).

Usage:
    python3 tests/eval_classifier.py                 # report mode
    python3 tests/eval_classifier.py --min 0.80      # gate at 80%
    python3 tests/eval_classifier.py --json out.json # also emit machine-readable summary
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Make the repo root importable so we can reach prompt_classifier.py
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

LABELS = ["APPROVAL", "REFINEMENT", "CORRECTION", "NEW_TASK"]


def load_eval(path: Path) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def confusion_matrix(rows: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    cm = {y: {p: 0 for p in LABELS} for y in LABELS}
    for true, pred in rows:
        cm[true][pred] += 1
    return cm


def per_class_metrics(cm: dict[str, dict[str, int]]) -> dict[str, dict[str, float]]:
    out = {}
    for label in LABELS:
        tp = cm[label][label]
        fn = sum(cm[label][p] for p in LABELS if p != label)
        fp = sum(cm[other][label] for other in LABELS if other != label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        out[label] = {"precision": precision, "recall": recall, "f1": f1, "support": tp + fn}
    return out


def render_matrix(cm: dict[str, dict[str, int]]) -> str:
    header = "true\\pred  | " + " ".join(f"{l[:4]:>5}" for l in LABELS)
    lines = [header, "-" * len(header)]
    for label in LABELS:
        row = " ".join(f"{cm[label][p]:>5}" for p in LABELS)
        lines.append(f"{label:<10} | {row}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", default=str(Path(__file__).parent / "eval.json"))
    ap.add_argument("--min", type=float, default=0.0,
                    help="Minimum overall accuracy to pass (0.0 = report only)")
    ap.add_argument("--json", default=None,
                    help="Optional path to write a JSON summary")
    args = ap.parse_args()

    eval_path = Path(args.eval)
    if not eval_path.exists():
        print(f"eval dataset not found: {eval_path}", file=sys.stderr)
        return 2

    examples = load_eval(eval_path)
    print(f"Loaded {len(examples)} eval pairs from {eval_path.name}")

    # Lazy import so the script can fail fast with a useful message if deps are missing
    try:
        from prompt_classifier import PromptClassifier
    except ImportError as e:
        print(f"Cannot import PromptClassifier: {e}", file=sys.stderr)
        print("Hint: run setup-venv.sh and use $RETRO_DAILY_DATA/.venv/bin/python3", file=sys.stderr)
        return 2

    print("Loading classifier (first run downloads model)...")
    clf = PromptClassifier()

    rows = []
    for ex in examples:
        result = clf.classify_pair(ex["prompt"], ex["reaction"])
        rows.append((ex["label"], result["category"]))

    correct = sum(1 for t, p in rows if t == p)
    accuracy = correct / len(rows)
    cm = confusion_matrix(rows)
    metrics = per_class_metrics(cm)

    print()
    print(f"Overall accuracy: {accuracy:.1%}  ({correct}/{len(rows)})")
    print()
    print("Confusion matrix:")
    print(render_matrix(cm))
    print()
    print(f"{'class':<11} {'precision':>10} {'recall':>10} {'f1':>10} {'support':>10}")
    for label in LABELS:
        m = metrics[label]
        print(f"{label:<11} {m['precision']:>10.2%} {m['recall']:>10.2%} {m['f1']:>10.2%} {m['support']:>10}")

    if args.json:
        summary = {
            "accuracy": accuracy,
            "n": len(rows),
            "confusion_matrix": cm,
            "per_class": metrics,
        }
        Path(args.json).write_text(json.dumps(summary, indent=2))
        print(f"\nWrote summary to {args.json}")

    if args.min and accuracy < args.min:
        print(f"\nFAIL: accuracy {accuracy:.1%} < min {args.min:.1%}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
