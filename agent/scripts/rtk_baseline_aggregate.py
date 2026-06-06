"""Aggregate cost_tracking.jsonl over a window to produce the rtk baseline / post-install evidence file.

Used by Chain B (#971 / #973) of the operator-gated runbook. Reads the bridge's
``cost_tracking.jsonl`` (per-request CostEntry append-only log) and produces a
markdown summary with:

  - Total cost (USD) over the window
  - Per-model breakdown (haiku/sonnet/opus)
  - Daily timeseries
  - Total request count + estimated total tokens

For the rtk baseline measurement, the operator runs this twice:

  # After 7 days off rtk (Sprint 01.05a / #971)
  python -m scripts.rtk_baseline_aggregate \\
      --start 2026-05-08T00:00:00Z \\
      --end 2026-05-15T00:00:00Z \\
      --output .harness/evidence/quick-wins/01.05a-baseline-week.md

  # After 7 days on rtk (Sprint 01.05c / #973)
  python -m scripts.rtk_baseline_aggregate \\
      --start 2026-05-22T00:00:00Z \\
      --end 2026-05-29T00:00:00Z \\
      --output .harness/evidence/quick-wins/01.05c-post-install-week.md

A separate hand-written delta-analysis writeup compares the two evidence files.

Usage requires no external dependencies — stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DEFAULT_DATA_DIR = Path("/opt/bumba-harness/data")
DEFAULT_FILENAME = "cost_tracking.jsonl"


def _parse_iso(s: str) -> datetime:
    """Parse an ISO-8601 timestamp; accept Z or +00:00."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _read_entries(path: Path, start: datetime, end: datetime):
    """Yield JSONL entries whose timestamp falls within [start, end)."""
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts_raw = entry.get("timestamp", "")
            if not ts_raw:
                continue
            try:
                ts = _parse_iso(ts_raw)
            except ValueError:
                continue
            if start <= ts < end:
                yield entry


def aggregate(entries) -> dict:
    """Reduce a stream of CostEntry dicts into the summary structure."""
    total_cost = 0.0
    total_in_tokens = 0
    total_out_tokens = 0
    total_count = 0
    by_model: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0}
    )
    by_day: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0}
    )

    for e in entries:
        cost = float(e.get("estimated_cost", 0.0))
        in_tokens = int(e.get("input_tokens", 0))
        out_tokens = int(e.get("output_tokens", 0))
        model = (e.get("model") or "unknown").lower()
        ts = _parse_iso(e["timestamp"])
        day = ts.strftime("%Y-%m-%d")

        total_cost += cost
        total_in_tokens += in_tokens
        total_out_tokens += out_tokens
        total_count += 1

        by_model[model]["count"] += 1
        by_model[model]["cost_usd"] += cost
        by_model[model]["input_tokens"] += in_tokens
        by_model[model]["output_tokens"] += out_tokens

        by_day[day]["count"] += 1
        by_day[day]["cost_usd"] += cost
        by_day[day]["input_tokens"] += in_tokens
        by_day[day]["output_tokens"] += out_tokens

    return {
        "total_cost_usd": round(total_cost, 4),
        "total_count": total_count,
        "total_input_tokens": total_in_tokens,
        "total_output_tokens": total_out_tokens,
        "by_model": {k: {**v, "cost_usd": round(v["cost_usd"], 4)} for k, v in sorted(by_model.items())},
        "by_day": {k: {**v, "cost_usd": round(v["cost_usd"], 4)} for k, v in sorted(by_day.items())},
    }


def render_markdown(
    summary: dict, start: datetime, end: datetime, source_path: Path, label: str
) -> str:
    """Format the aggregated summary as markdown for the evidence file."""
    days_in_window = (end - start).total_seconds() / 86400
    lines = []
    lines.append(f"# {label}")
    lines.append("")
    lines.append("## Window")
    lines.append("")
    lines.append(f"- Start (UTC): `{start.isoformat()}`")
    lines.append(f"- End (UTC):   `{end.isoformat()}`")
    lines.append(f"- Duration:    {days_in_window:.1f} days")
    lines.append(f"- Source:      `{source_path}`")
    lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append(f"- Requests:        {summary['total_count']:,}")
    lines.append(f"- Total cost:      ${summary['total_cost_usd']:.4f} USD")
    lines.append(f"- Input tokens:    {summary['total_input_tokens']:,}")
    lines.append(f"- Output tokens:   {summary['total_output_tokens']:,}")
    if days_in_window > 0:
        lines.append(
            f"- Avg cost / day:  ${summary['total_cost_usd'] / days_in_window:.4f} USD"
        )
    lines.append("")
    lines.append("## Per-model breakdown")
    lines.append("")
    lines.append("| Model | Requests | Cost (USD) | Input tokens | Output tokens |")
    lines.append("|---|---:|---:|---:|---:|")
    for model, m in summary["by_model"].items():
        lines.append(
            f"| {model} | {m['count']:,} | ${m['cost_usd']:.4f} | {m['input_tokens']:,} | {m['output_tokens']:,} |"
        )
    lines.append("")
    lines.append("## Daily timeseries")
    lines.append("")
    lines.append("| Day | Requests | Cost (USD) | Input tokens | Output tokens |")
    lines.append("|---|---:|---:|---:|---:|")
    for day, d in summary["by_day"].items():
        lines.append(
            f"| {day} | {d['count']:,} | ${d['cost_usd']:.4f} | {d['input_tokens']:,} | {d['output_tokens']:,} |"
        )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Bash tool invocations are not directly captured here — `cost_tracking.jsonl` "
        "is per-request, not per-tool-call. For rtk before/after comparison, "
        "the per-request cost delta is the load-bearing number; the rtk-supplied "
        "`rtk gain --json` provides the per-shell-command compression detail."
    )
    lines.append(
        "- Operator confirms baseline window covered normal usage (no service "
        "outage, no halt period) per Sprint 01.05a / 01.05c spec."
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--start",
        required=True,
        help="Window start (ISO-8601 UTC, e.g. 2026-05-08T00:00:00Z)",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="Window end (ISO-8601 UTC; exclusive)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Directory containing cost_tracking.jsonl (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--filename",
        default=DEFAULT_FILENAME,
        help=f"JSONL filename (default: {DEFAULT_FILENAME})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write markdown to this path (default: stdout)",
    )
    parser.add_argument(
        "--label",
        default="Cost baseline",
        help="Heading for the evidence file (e.g. '01.05a Pre-rtk Baseline Week')",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the aggregated summary as JSON instead of markdown",
    )
    args = parser.parse_args(argv)

    try:
        start = _parse_iso(args.start)
        end = _parse_iso(args.end)
    except ValueError as exc:
        print(f"ERROR: bad timestamp: {exc}", file=sys.stderr)
        return 2

    if start >= end:
        print("ERROR: --start must be before --end", file=sys.stderr)
        return 2

    source_path = args.data_dir / args.filename
    if not source_path.exists():
        print(f"ERROR: source file not found: {source_path}", file=sys.stderr)
        return 3

    entries = list(_read_entries(source_path, start, end))
    summary = aggregate(entries)

    if args.json:
        out = json.dumps(summary, indent=2)
    else:
        out = render_markdown(summary, start, end, source_path, args.label)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(out, encoding="utf-8")
        print(f"Wrote {args.output} ({summary['total_count']} entries summarised)")
    else:
        print(out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
