"""Nightly Zone 4 cost rollup.

Aggregates sessions/*/cost.json by department x tool and writes a daily
summary to data/z4-cost-daily-YYYYMMDD.json.

Runs nightly at 01:00 via com.bumba.agent-cost-rollup LaunchDaemon.
Answers operator questions like:
  - "Which department cost the most this week?"
  - "Cost-per-successful-run by department this month?"

Usage:
    python scripts/cost_rollup.py               # rollup for today
    python scripts/cost_rollup.py --date YYYYMMDD  # rollup for a specific date
    python scripts/cost_rollup.py --dry-run     # print summary, don't write
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_SESSIONS_DIR = Path("/opt/bumba-harness/sessions")
_DEFAULT_DATA_DIR = Path("/opt/bumba-harness/data")


# ---------------------------------------------------------------------------
# Core rollup logic
# ---------------------------------------------------------------------------

def _iter_session_cost_files(sessions_dir: Path) -> list[Path]:
    """Return all cost.json files under sessions_dir, sorted by path."""
    if not sessions_dir.exists():
        return []
    return sorted(sessions_dir.glob("*/cost.json"))


def _session_date(cost_file: Path) -> str | None:
    """Return the date string (YYYY-MM-DD) for a session from its meta.json.

    Falls back to the directory mtime if meta.json is absent.
    Returns None if the date cannot be determined.
    """
    session_dir = cost_file.parent
    meta_path = session_dir / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            # meta.json stores ISO timestamp in "created_at"
            created_at = meta.get("created_at", "")
            if created_at:
                return created_at[:10]  # YYYY-MM-DD
        except (json.JSONDecodeError, OSError):
            pass
    # Fall back to directory mtime
    try:
        mtime = session_dir.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")
    except OSError:
        return None


def _parse_cost_file(cost_file: Path) -> dict:
    """Parse a cost.json file. Returns empty dict on error."""
    try:
        return json.loads(cost_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def rollup(
    target_date: str,
    *,
    sessions_dir: Path = _DEFAULT_SESSIONS_DIR,
    data_dir: Path = _DEFAULT_DATA_DIR,
    dry_run: bool = False,
) -> dict:
    """Aggregate sessions/*/cost.json for target_date.

    Args:
        target_date: Date string in YYYY-MM-DD format.
        sessions_dir: Root directory of session folders.
        data_dir: Root directory for writing output JSON.
        dry_run: If True, compute but do not write output file.

    Returns:
        The computed rollup dict (written to data_dir if not dry_run).
    """
    cost_files = _iter_session_cost_files(sessions_dir)

    # Structures: by_department[dept][tool] = {cost, calls, tokens}
    by_department: dict[str, dict[str, dict]] = defaultdict(
        lambda: defaultdict(lambda: {"cost_usd": 0.0, "calls": 0, "input_tokens": 0, "output_tokens": 0})
    )
    dept_sessions: dict[str, int] = defaultdict(int)
    dept_blocked: dict[str, int] = defaultdict(int)
    sessions_processed = 0
    sessions_skipped = 0

    for cost_file in cost_files:
        date_str = _session_date(cost_file)
        if date_str != target_date:
            sessions_skipped += 1
            continue

        data = _parse_cost_file(cost_file)
        if not data:
            sessions_skipped += 1
            continue

        sessions_processed += 1

        # cost.json structure (from SessionCostSummary.to_dict()):
        # {
        #   "session_id": "...",
        #   "departments": [
        #     {
        #       "department": "qa",
        #       "agents": [{"agent_name": "qa-chief", "total_usd": 0.05, ...}],
        #       "total_usd": 0.07,
        #       "call_count": 5,
        #       "blocked_calls": 0,
        #       ...
        #     }
        #   ]
        # }
        departments = data.get("departments", [])
        for dept_data in departments:
            dept_name = dept_data.get("department", "unknown")
            dept_sessions[dept_name] += 1
            dept_blocked[dept_name] += dept_data.get("blocked_calls", 0)

            for agent_data in dept_data.get("agents", []):
                agent_name = agent_data.get("agent_name", "unknown")
                by_department[dept_name][agent_name]["cost_usd"] += agent_data.get("total_usd", 0.0)
                by_department[dept_name][agent_name]["calls"] += agent_data.get("call_count", 0)
                by_department[dept_name][agent_name]["input_tokens"] += agent_data.get("total_input_tokens", 0)
                by_department[dept_name][agent_name]["output_tokens"] += agent_data.get("total_output_tokens", 0)

    # Build final structure
    dept_totals: dict[str, dict] = {}
    grand_total_usd = 0.0
    grand_total_calls = 0

    for dept, agents in by_department.items():
        dept_total_usd = sum(v["cost_usd"] for v in agents.values())
        dept_total_calls = sum(v["calls"] for v in agents.values())
        grand_total_usd += dept_total_usd
        grand_total_calls += dept_total_calls
        dept_totals[dept] = {
            "total_cost_usd": round(dept_total_usd, 6),
            "total_calls": dept_total_calls,
            "session_count": dept_sessions.get(dept, 0),
            "blocked_calls": dept_blocked.get(dept, 0),
            "agents": {
                agent: {
                    "cost_usd": round(v["cost_usd"], 6),
                    "calls": v["calls"],
                    "input_tokens": v["input_tokens"],
                    "output_tokens": v["output_tokens"],
                }
                for agent, v in agents.items()
            },
        }

    rollup_result = {
        "date": target_date,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "sessions_processed": sessions_processed,
        "grand_total_cost_usd": round(grand_total_usd, 6),
        "grand_total_calls": grand_total_calls,
        "by_department": dict(dept_totals),
    }

    if not dry_run:
        date_compact = target_date.replace("-", "")
        out_path = data_dir / f"z4-cost-daily-{date_compact}.json"
        data_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(rollup_result, indent=2), encoding="utf-8")
        print(f"Wrote {out_path}", flush=True)
    else:
        print(json.dumps(rollup_result, indent=2), flush=True)

    return rollup_result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Nightly Zone 4 cost rollup — aggregates sessions/*/cost.json."
    )
    parser.add_argument(
        "--date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        help="Target date in YYYY-MM-DD format (default: today UTC).",
    )
    parser.add_argument(
        "--sessions-dir",
        default=str(_DEFAULT_SESSIONS_DIR),
        help=f"Sessions root directory (default: {_DEFAULT_SESSIONS_DIR}).",
    )
    parser.add_argument(
        "--data-dir",
        default=str(_DEFAULT_DATA_DIR),
        help=f"Data output directory (default: {_DEFAULT_DATA_DIR}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary to stdout; do not write output file.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = rollup(
        target_date=args.date,
        sessions_dir=Path(args.sessions_dir),
        data_dir=Path(args.data_dir),
        dry_run=args.dry_run,
    )
    depts = result.get("by_department", {})
    total = result.get("grand_total_cost_usd", 0.0)
    print(
        f"Rollup complete: date={result['date']} "
        f"sessions={result['sessions_processed']} "
        f"depts={len(depts)} "
        f"total=${total:.4f}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
