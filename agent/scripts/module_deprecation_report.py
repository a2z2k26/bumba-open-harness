#!/usr/bin/env python3
"""Module Deprecation Analysis Report (#24).

Reads telemetry from data/metrics.jsonl and response evaluations from
data/evaluation_log.jsonl to compute a keep_score for each of the 6
candidate modules:

    keep_score = usage_frequency * quality_impact_delta + dependency_count * 0.5

Where:
    usage_frequency    = counter / total_sessions (normalized, 0-1+)
    quality_impact_delta = avg eval score with module active - avg score without
                           (from few_shot A/B data; 0 if no A/B data available)
    dependency_count   = number of other bridge modules that import this module
                         (static analysis via grep)

Recommendations:
    < 1.0  → "deprecate candidate"
    1.0-3.0 → "simplify candidate"
    > 3.0  → "keep"

Output: printed to stdout + saved to data/deprecation_report.json.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
AGENT_DIR = SCRIPT_DIR.parent
DATA_DIR = AGENT_DIR / "data"
BRIDGE_DIR = AGENT_DIR / "bridge"

METRICS_JSONL = DATA_DIR / "metrics.jsonl"
EVAL_LOG_JSONL = DATA_DIR / "evaluation_log.jsonl"
REPORT_JSON = DATA_DIR / "deprecation_report.json"

# Candidate modules: counter key → (module file, display label)
CANDIDATES: dict[str, tuple[str, str]] = {
    "few_shot_injections":    ("few_shot.py",            "few_shot"),
    "model_router_overrides": ("model_router.py",        "model_router"),
    "department_detections":  ("departments.py",         "departments"),
    "temporal_kb_queries":    ("temporal_knowledge.py",  "temporal_knowledge"),
    "self_edit_requests":     ("self_edit_memory.py",    "self_edit_memory"),
    "reflection_retrievals":  ("reflection.py",          "reflection"),
}

SCORE_DEPRECATE = 1.0
SCORE_SIMPLIFY = 3.0


# ---------------------------------------------------------------------------
# Telemetry reader
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> list[dict]:
    """Load all JSON lines from a JSONL file.  Returns empty list if missing."""
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def aggregate_counters(entries: list[dict]) -> dict[str, int]:
    """Sum counter values across all metrics.jsonl entries."""
    totals: dict[str, int] = {}
    for entry in entries:
        for k, v in entry.get("counters", {}).items():
            totals[k] = totals.get(k, 0) + int(v)
    return totals


def count_sessions(entries: list[dict]) -> int:
    """Estimate total sessions from metrics entries (each flush ~ one period)."""
    # Use messages_total counter as proxy; fall back to entry count
    totals = aggregate_counters(entries)
    if "messages_total" in totals and totals["messages_total"] > 0:
        return totals["messages_total"]
    return max(len(entries), 1)


# ---------------------------------------------------------------------------
# A/B quality impact
# ---------------------------------------------------------------------------

def compute_quality_impact(eval_entries: list[dict]) -> float:
    """Compute avg eval score with few_shot=True minus avg score with few_shot=False.

    Returns 0.0 if insufficient data in either group.
    """
    with_fs = [e["overall"] for e in eval_entries if e.get("few_shot_active") is True]
    without_fs = [e["overall"] for e in eval_entries if e.get("few_shot_active") is False]

    if len(with_fs) < 3 or len(without_fs) < 3:
        return 0.0  # Not enough A/B data yet

    avg_with = sum(with_fs) / len(with_fs)
    avg_without = sum(without_fs) / len(without_fs)
    return avg_with - avg_without


# ---------------------------------------------------------------------------
# Static dependency analysis
# ---------------------------------------------------------------------------

def count_dependents(module_file: str) -> int:
    """Count bridge/*.py files (excluding the module itself) that import module_file."""
    # Derive the import name from the filename: few_shot.py → few_shot
    module_name = module_file.replace(".py", "").replace("-", "_")
    count = 0
    if not BRIDGE_DIR.exists():
        return 0
    for py_file in BRIDGE_DIR.glob("*.py"):
        if py_file.name == module_file:
            continue
        try:
            src = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Match: from .few_shot import ... OR import bridge.few_shot OR from bridge.few_shot import
        if re.search(
            rf"from\s+\.{re.escape(module_name)}\s+import|"
            rf"import\s+bridge\.{re.escape(module_name)}|"
            rf"from\s+bridge\.{re.escape(module_name)}\s+import",
            src,
        ):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Score and recommendation
# ---------------------------------------------------------------------------

def recommend(score: float) -> str:
    if score < SCORE_DEPRECATE:
        return "deprecate candidate"
    if score <= SCORE_SIMPLIFY:
        return "simplify candidate"
    return "keep"


# ---------------------------------------------------------------------------
# Main report
# ---------------------------------------------------------------------------

def generate_report() -> dict:
    """Generate and return the full deprecation report."""
    metric_entries = load_jsonl(METRICS_JSONL)
    eval_entries = load_jsonl(EVAL_LOG_JSONL)

    counters = aggregate_counters(metric_entries)
    total_sessions = count_sessions(metric_entries)
    quality_impact = compute_quality_impact(eval_entries)

    modules: list[dict] = []
    for counter_key, (module_file, label) in CANDIDATES.items():
        raw_count = counters.get(counter_key, 0)
        usage_frequency = raw_count / total_sessions  # normalized 0-1+
        dep_count = count_dependents(module_file)

        # few_shot A/B data informs quality_impact_delta for ALL modules since
        # it's the only module with an explicit A/B flag; others default to 0.
        module_quality_delta = quality_impact if counter_key == "few_shot_injections" else 0.0

        keep_score = usage_frequency * module_quality_delta + dep_count * 0.5
        modules.append({
            "module": label,
            "counter_key": counter_key,
            "raw_count": raw_count,
            "total_sessions": total_sessions,
            "usage_frequency": round(usage_frequency, 4),
            "quality_impact_delta": round(module_quality_delta, 4),
            "dependency_count": dep_count,
            "keep_score": round(keep_score, 4),
            "recommendation": recommend(keep_score),
        })

    modules.sort(key=lambda m: m["keep_score"], reverse=True)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_sources": {
            "metrics_entries": len(metric_entries),
            "eval_entries": len(eval_entries),
            "total_sessions_proxy": total_sessions,
        },
        "ab_quality_impact": round(quality_impact, 4),
        "modules": modules,
    }
    return report


def print_report(report: dict) -> None:
    """Print the report to stdout in a human-readable format."""
    print("# Module Deprecation Analysis")
    print(f"Generated: {report['generated_at']}")
    ds = report["data_sources"]
    print(
        f"Data: {ds['metrics_entries']} metric entries, "
        f"{ds['eval_entries']} eval entries, "
        f"~{ds['total_sessions_proxy']} sessions"
    )
    ab = report["ab_quality_impact"]
    if abs(ab) > 0:
        print(f"A/B quality impact (few_shot): {ab:+.3f} score points")
    else:
        print("A/B quality impact: no data yet (need few_shot_enabled toggled)")
    print()
    print(
        f"{'Module':<22} | {'Score':>6} | {'Usage':>8} | {'Deps':>4} | Recommendation"
    )
    print(f"{'-'*22}-+-{'-'*6}-+-{'-'*8}-+-{'-'*4}-+-{'-'*22}")
    for m in report["modules"]:
        print(
            f"{m['module']:<22} | {m['keep_score']:>6.2f} | "
            f"{m['usage_frequency']:>8.4f} | {m['dependency_count']:>4} | "
            f"{m['recommendation']}"
        )
    print()
    print("Score formula: keep_score = usage_frequency * quality_impact_delta + dependency_count * 0.5")
    print("Thresholds: < 1.0 → deprecate | 1.0-3.0 → simplify | > 3.0 → keep")


def save_report(report: dict) -> None:
    """Save report to data/deprecation_report.json."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"Warning: could not save report to {REPORT_JSON}: {e}", file=sys.stderr)


def main() -> None:
    report = generate_report()
    print_report(report)
    save_report(report)


if __name__ == "__main__":
    main()
