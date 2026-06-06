"""Lint the sprint dependency graph (D7.6).

Reads `docs/sprint-dependency-graph.json` (produced by
`build_sprint_dependency_graph.py`) and the live state of every open
issue. Reports issues whose declared prereqs are still open and might
block their next move.

Two modes:

  default   WARN-only — exit 0, prints findings to stdout
  --strict  exit non-zero if any open issue has an open prereq

Useful as a pre-PR check (warn) and a CI gate after dep-graph backfill
lands (strict).

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GRAPH_PATH = REPO_ROOT / "docs" / "sprint-dependency-graph.json"


def fetch_issue_states(numbers: list[int]) -> dict[int, str]:
    """Return {issue_number: state} for every issue in `numbers` (live gh)."""
    if not numbers:
        return {}
    states: dict[int, str] = {}
    # gh issue view is 1-at-a-time; use issue list with a search to batch
    # query state by number — fall back to single-issue calls if needed.
    # Simplest reliable path: per-issue calls (slow for large N but we
    # only call this against issues that DO have edges, typically <50).
    for n in numbers:
        try:
            result = subprocess.run(
                ["gh", "issue", "view", str(n), "--json", "state"],
                capture_output=True, text=True, check=True,
            )
            states[n] = json.loads(result.stdout).get("state", "UNKNOWN")
        except subprocess.CalledProcessError:
            states[n] = "UNKNOWN"
    return states


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--graph-path",
        type=Path,
        default=DEFAULT_GRAPH_PATH,
        help=f"Path to sprint-dependency-graph.json (default: {DEFAULT_GRAPH_PATH})",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any open issue has an open prereq",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Don't query gh — assume all referenced issues are open (for testing)",
    )
    args = parser.parse_args(argv)

    if not args.graph_path.exists():
        print(
            f"ERROR: graph file not found at {args.graph_path}. "
            "Run scripts/build_sprint_dependency_graph.py first.",
            file=sys.stderr,
        )
        return 2

    with args.graph_path.open("r", encoding="utf-8") as fh:
        graph = json.load(fh)

    nodes = {n["number"]: n for n in graph["nodes"]}
    edges = graph["edges"]

    # Collect (downstream, upstream-prereq) pairs from the prereq edges.
    # An edge {from: P, to: D, kind: prereq} means P is a prereq of D.
    prereq_pairs: list[tuple[int, int]] = [
        (e["to"], e["from"]) for e in edges if e["kind"] == "prereq"
    ]
    referenced = sorted({p for _, p in prereq_pairs} | {d for d, _ in prereq_pairs})
    if args.offline:
        states = {n: "OPEN" for n in referenced}
    else:
        states = fetch_issue_states(referenced)

    findings: list[str] = []
    for downstream, upstream in prereq_pairs:
        ds_state = states.get(downstream, "UNKNOWN")
        us_state = states.get(upstream, "UNKNOWN")
        # Only warn when downstream is OPEN AND upstream is OPEN — that's
        # the case where the work can't actually start.
        if ds_state == "OPEN" and us_state == "OPEN":
            ds_node = nodes.get(downstream, {})
            us_node = nodes.get(upstream, {})
            findings.append(
                f"#{downstream} ({ds_node.get('slug') or '—'}: "
                f"{ds_node.get('title', '')[:60]}) "
                f"blocked by open prereq #{upstream} "
                f"({us_node.get('slug') or '—'}: "
                f"{us_node.get('title', '')[:60]})"
            )

    if not findings:
        print("✓ No open issues have open prereqs.")
        return 0

    print(f"⚠ {len(findings)} open issues have open prereqs:")
    for f in findings:
        print(f"  - {f}")

    if args.strict:
        print("\nFAIL: --strict mode; exit non-zero.")
        return 1

    print(
        "\nWARN: dependency-graph linter found prereq violations. "
        "Re-run with --strict to gate CI when backfill lands."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
