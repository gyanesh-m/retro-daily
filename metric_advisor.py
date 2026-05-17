"""
Metric delta computation, threshold evaluation, and metric-to-action mapping.
Maps weak metrics to specific recommendations and GitHub search queries for tool scouting.
"""
import json
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path


METRIC_THRESHOLDS = {
    "edit_read_ratio": {"good": 1.0, "warn": 0.5, "direction": "higher_better"},
    "auto_rate": {"good": 80, "warn": 70, "direction": "higher_better"},
    "first_try_rate": {"good": 70, "warn": 55, "direction": "higher_better"},
    "correction_rate": {"good": 5, "warn": 15, "direction": "lower_better"},
    "tool_error_rate": {"good": 3, "warn": 8, "direction": "lower_better"},
    # % of sessions with >40 real user turns that used /compact (higher = better hygiene)
    # None when no long sessions have occurred — metric is skipped automatically.
    "ctx_compact_rate": {"good": 70, "warn": 40, "direction": "higher_better"},
}

METRIC_ACTIONS = {
    "edit_read_ratio": {
        "warn": {
            "recommendation": "Use code graph MCP (semantic_search_nodes) for targeted reads instead of full files",
            "search_queries": ["claude code graph MCP server", "claude code targeted file reading tool"],
        },
        "bad": {
            "recommendation": "Too much browsing, not enough editing. Use offset/limit reads. Query graph before reading.",
            "search_queries": ["claude code context efficiency", "claude code file reading optimization"],
        },
    },
    "auto_rate": {
        "warn": {
            "recommendation": "Review auto-approve rules. Add frequently-approved tool patterns to settings.json allowedTools",
            "search_queries": ["claude code auto approve configuration", "claude code permission management hooks"],
        },
        "bad": {
            "recommendation": "Most tools need manual approval. Consider dangerously-skip-permissions in sandboxed envs or add allowedTools",
            "search_queries": ["claude code sandbox permissions", "claude code auto approve setup"],
        },
    },
    "first_try_rate": {
        "warn": {
            "recommendation": "Use /brainstorm before complex tasks. Update CLAUDE.md with project-specific patterns.",
            "search_queries": ["claude code planning skill", "claude code CLAUDE.md best practices 2026"],
        },
        "bad": {
            "recommendation": "Many prompts need correction. Decompose tasks. Use specification-first workflow.",
            "search_queries": ["claude code task decomposition agent", "claude code specification workflow"],
        },
    },
    "correction_rate": {
        "warn": {
            "recommendation": "Update CLAUDE.md with project-specific conventions to reduce misunderstandings",
            "search_queries": ["claude code CLAUDE.md templates", "claude code project context management"],
        },
        "bad": {
            "recommendation": "High correction rate. Split complex prompts. Use /compact between focus changes.",
            "search_queries": ["claude code session management", "claude code prompt engineering tips"],
        },
    },
    "tool_error_rate": {
        "warn": {
            "recommendation": "Tool errors detected (likely file-not-read before edit). Ensure read-before-write in CLAUDE.md.",
            "search_queries": ["claude code workflow patterns", "claude code tool error prevention"],
        },
        "bad": {
            "recommendation": "Many tool failures. Check CLAUDE.md for missing workflow instructions or stale file paths.",
            "search_queries": ["claude code error handling patterns", "claude code CLAUDE.md audit tool"],
        },
    },
    "ctx_compact_rate": {
        "warn": {
            "recommendation": "Some long sessions run past 40 turns without /compact — corrections tend to spike in the back half. Compact at natural task boundaries.",
            "search_queries": ["claude code compact session management", "claude code context window tips"],
        },
        "bad": {
            "recommendation": "Most long sessions never compact. Use /compact between focus changes or when switching sub-tasks — restores model accuracy and cuts cache costs.",
            "search_queries": ["claude code session management", "claude code context window management compaction"],
        },
    },
}

# Cross-reference: (weak_metric, session_topic) -> topic-specific advice
TOPIC_SPECIFIC_ADVICE = {
    ("first_try_rate", "swift_ios"): "Add Swift/Xcode build commands and project structure to CLAUDE.md",
    ("first_try_rate", "web_frontend"): "Provide component specs and design tokens before building UI",
    ("first_try_rate", "devops"): "Include deployment scripts and environment details in CLAUDE.md",
    ("first_try_rate", "api_backend"): "Document API schema and database models in CLAUDE.md",
    ("tool_error_rate", "swift_ios"): "File-not-read errors suggest Xcode project structure confusion. Use code graph MCP.",
    ("tool_error_rate", "web_frontend"): "File-not-read errors in web projects — ensure component paths documented in CLAUDE.md",
    ("correction_rate", "configuration"): "Configuration tasks have high correction rates — add env setup steps to CLAUDE.md",
    ("correction_rate", "devops"): "DevOps corrections often come from missing context — document infra state in CLAUDE.md",
    ("edit_read_ratio", "debugging"): "Debugging sessions are read-heavy by nature — this is expected, not a problem",
    ("edit_read_ratio", "exploration"): "Exploration sessions are read-heavy by nature — this is expected, not a problem",
}


def compute_deltas(store: Dict, windows: List[int] = None) -> Dict:
    """
    Compute metric deltas across time windows.
    For each metric, compare most recent value against window averages.

    Returns: {metric: {value: X, "7d": +/-X, "15d": +/-X, "30d": +/-X}}
    """
    if windows is None:
        windows = [7, 15, 30]

    daily = store.get("daily", {})
    cumulative = store.get("cumulative", {})
    if not daily:
        return {}

    sorted_dates = sorted(daily.keys(), reverse=True)
    metrics_to_track = ["edit_read_ratio", "auto_rate", "first_try_rate", "correction_rate", "tool_error_rate", "ctx_compact_rate"]

    # Get most recent value for each metric
    recent_date = sorted_dates[0]
    recent = daily[recent_date]

    result = {}
    for metric in metrics_to_track:
        current_val = recent.get(metric, cumulative.get(metric, 0))
        if current_val is None:
            current_val = 0

        deltas = {}
        for window in windows:
            cutoff = (date.fromisoformat(recent_date) - timedelta(days=window)).isoformat()
            window_values = [
                daily[d].get(metric, 0)
                for d in sorted_dates
                if d >= cutoff and daily[d].get(metric) is not None
            ]

            if window_values:
                window_avg = sum(window_values) / len(window_values)
                delta = round(current_val - window_avg, 1)
                deltas[f"{window}d"] = delta
            else:
                deltas[f"{window}d"] = None  # Not enough data

        result[metric] = {"value": current_val, **deltas}

    return result


def evaluate_metrics(store: Dict, topics: Optional[List[str]] = None) -> List[Dict]:
    """
    Evaluate metrics against thresholds.
    Returns list of weak metrics with recommendations and search queries.
    Only includes metrics that are WARN or BAD.
    """
    cumulative = store.get("cumulative", {})
    # Also check most recent day for tool_error_rate (not in cumulative yet for old stores)
    daily = store.get("daily", {})
    sorted_dates = sorted(daily.keys(), reverse=True)
    recent = daily[sorted_dates[0]] if sorted_dates else {}

    weak = []
    for metric, thresholds in METRIC_THRESHOLDS.items():
        value = cumulative.get(metric, recent.get(metric))
        if value is None:
            continue

        direction = thresholds["direction"]
        good = thresholds["good"]
        warn = thresholds["warn"]

        if direction == "higher_better":
            if value >= good:
                severity = "good"
            elif value >= warn:
                severity = "warn"
            else:
                severity = "bad"
        else:  # lower_better
            if value <= good:
                severity = "good"
            elif value <= warn:
                severity = "warn"
            else:
                severity = "bad"

        if severity == "good":
            continue

        action = METRIC_ACTIONS.get(metric, {}).get(severity, {})
        recommendation = action.get("recommendation", "")
        search_queries = action.get("search_queries", [])

        # Check for topic-specific advice
        topic_advice = None
        if topics:
            for topic in topics:
                key = (metric, topic)
                if key in TOPIC_SPECIFIC_ADVICE:
                    topic_advice = TOPIC_SPECIFIC_ADVICE[key]
                    break

        weak.append({
            "metric": metric,
            "value": value,
            "severity": severity.upper(),
            "recommendation": topic_advice or recommendation,
            "search_queries": search_queries,
            "is_topic_specific": topic_advice is not None,
        })

    return weak


def format_delta_arrow(delta: Optional[float], direction: str) -> str:
    """Format a delta value with direction arrow. ^ = improvement, v = degradation, -> = stable."""
    if delta is None:
        return "?"

    if abs(delta) < 0.5:
        return "->"

    if direction == "higher_better":
        return f"^{abs(delta)}" if delta > 0 else f"v{abs(delta)}"
    else:  # lower_better
        return f"^{abs(delta)}" if delta < 0 else f"v{abs(delta)}"


def format_metric_line(metric: str, deltas: Dict, windows: List[int] = None) -> str:
    """
    Format a single metric with deltas.
    e.g. "Edit/Read 1.2 (->7d | ^0.3 15d | ^0.3 30d)"
    """
    if windows is None:
        windows = [7, 15, 30]

    display_names = {
        "edit_read_ratio": "Edit/Read",
        "auto_rate": "Auto",
        "first_try_rate": "FirstTry",
        "correction_rate": "Corrections",
        "tool_error_rate": "ToolErr",
    }
    suffixes = {
        "auto_rate": "%",
        "first_try_rate": "%",
        "correction_rate": "%",
        "tool_error_rate": "%",
    }
    directions = {m: t["direction"] for m, t in METRIC_THRESHOLDS.items()}

    name = display_names.get(metric, metric)
    value = deltas.get("value", 0)
    suffix = suffixes.get(metric, "")
    direction = directions.get(metric, "higher_better")

    parts = []
    for w in windows:
        d = deltas.get(f"{w}d")
        arrow = format_delta_arrow(d, direction)
        parts.append(f"{arrow} {w}d")

    return f"{name} {value}{suffix} ({' | '.join(parts)})"


def load_analysis_history(metrics_dir: str = None) -> Dict:
    """Load or initialize analysis history."""
    if metrics_dir is None:
        metrics_dir = str(Path.home() / ".claude" / "metrics")
    path = Path(metrics_dir) / "analysis-history.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {
        "last_analysis": None,
        "last_scout": None,
        "weak_metrics_history": [],
        "scouted_repos": [],
        "recommendations_given": [],
    }


def save_analysis_history(history: Dict, metrics_dir: str = None):
    """Save analysis history."""
    if metrics_dir is None:
        metrics_dir = str(Path.home() / ".claude" / "metrics")
    path = Path(metrics_dir) / "analysis-history.json"
    with open(path, "w") as f:
        json.dump(history, f, indent=2)
