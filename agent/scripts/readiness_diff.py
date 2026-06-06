"""Diff two readiness reports and surface status changes.

Sprint R3.3 (current-state improvement plan) — once R1.5 made
``make readiness-strict`` the release gate, the operator needs a way to
prove a branch did not regress against a baseline before merging or
releasing. ``data/readiness-report.md`` is gitignored and overwritten on
every run, so trend analysis demands a small comparison utility rather
than eyeballing two reports.

Usage
-----
::

    python3 agent/scripts/readiness_diff.py \
        --old <baseline.md> \
        --new <data/readiness-report.md>

    python3 agent/scripts/readiness_diff.py \
        --old <baseline.md> \
        --new <data/readiness-report.md> \
        --format json

Exit codes
----------
- ``0`` — no regressions (improvements and unchanged rows allowed).
- ``1`` — at least one regression: PASS → FAIL/PENDING, missing row, or
  renamed row without an alias mapping.
- ``2`` — internal harness error: file missing, parse failed, etc.

Design constraints
------------------
- **stdlib-only.** No ``yaml`` / ``markdown`` / ``rich`` import; this
  runs in CI, in fresh sandboxes, and on the Mac mini where keeping the
  dependency surface flat is part of the doctrine.
- **No mutation of inputs.** Every parse returns a new tuple of rows;
  every comparison returns a new ``DiffResult``.
- **PASS / FAIL / PENDING are the only stati recognised** — matches
  ``agent/scripts/readiness.sh::record_row``. Any other value parsed
  out of a report is preserved verbatim and treated as a regression
  candidate against PASS.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# Statuses that ``readiness.sh`` writes. ``record_row`` only emits these
# three; anything else parsed is treated as foreign and surfaced as a
# regression candidate.
_KNOWN_STATUSES = {"PASS", "FAIL", "PENDING"}

# Regression severity ordering. Used to flag transitions where the new
# status is *worse* than the old status.
_SEVERITY = {
    "PASS": 0,
    "PENDING": 1,
    "FAIL": 2,
}

_ROW_RE = re.compile(
    r"^\|\s*(?P<n>\d+)\s*\|\s*(?P<name>.+?)\s*\|\s*(?P<status>[A-Z]+)\s*\|\s*(?P<notes>.+?)\s*\|\s*$"
)


@dataclass(frozen=True)
class Row:
    """One parsed row from the report's ``## Checks`` table."""

    index: int
    name: str
    status: str
    notes: str


@dataclass(frozen=True)
class Transition:
    """One row's old → new status change."""

    name: str
    old_status: str
    new_status: str
    is_regression: bool
    is_improvement: bool

    def render(self) -> str:
        marker = "REGRESSION" if self.is_regression else (
            "improved" if self.is_improvement else "changed"
        )
        return f"  [{marker}] {self.name}: {self.old_status} → {self.new_status}"


@dataclass(frozen=True)
class DiffResult:
    """Structured comparison between two reports."""

    transitions: tuple[Transition, ...] = field(default_factory=tuple)
    added_rows: tuple[Row, ...] = field(default_factory=tuple)
    removed_rows: tuple[Row, ...] = field(default_factory=tuple)
    unchanged: tuple[Row, ...] = field(default_factory=tuple)

    @property
    def regressions(self) -> tuple[Transition, ...]:
        return tuple(t for t in self.transitions if t.is_regression)

    @property
    def improvements(self) -> tuple[Transition, ...]:
        return tuple(t for t in self.transitions if t.is_improvement)

    @property
    def has_regressions(self) -> bool:
        return bool(self.regressions) or bool(self.removed_rows)


def parse_report(text: str) -> tuple[Row, ...]:
    """Extract rows from the ``## Checks`` table of a readiness report.

    Tolerates leading/trailing whitespace, the header row, and the
    separator row. Returns rows in document order. Rows whose status is
    not in ``_KNOWN_STATUSES`` are still returned (verbatim status) so
    the diff can flag them.
    """
    rows: list[Row] = []
    in_checks = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not in_checks:
            if line.startswith("## Checks"):
                in_checks = True
            continue
        # Stop at the next H2 (the report's `## Detail` section etc.).
        if line.startswith("## "):
            break
        match = _ROW_RE.match(line)
        if not match:
            continue
        # Skip the markdown table separator row (the header row's status
        # cell would be ``------`` and won't match the status group, so
        # it's already filtered by the regex). Also skip the header
        # itself if it accidentally matches (defensive).
        if match.group("status") == "Status":
            continue
        rows.append(
            Row(
                index=int(match.group("n")),
                name=match.group("name").strip(),
                status=match.group("status").strip(),
                notes=match.group("notes").strip(),
            )
        )
    return tuple(rows)


def diff_reports(old: Iterable[Row], new: Iterable[Row]) -> DiffResult:
    """Return a structured diff of two parsed reports.

    Matches rows by ``name``. A row in ``old`` but not in ``new`` is a
    *removal* (always a regression). A row in ``new`` but not in
    ``old`` is an *addition* (not a regression). Rows present in both
    produce a ``Transition`` whose direction is computed from the
    severity table.
    """
    old_by_name = {r.name: r for r in old}
    new_by_name = {r.name: r for r in new}

    transitions: list[Transition] = []
    unchanged: list[Row] = []
    added_rows: list[Row] = []
    removed_rows: list[Row] = []

    for name, new_row in new_by_name.items():
        if name not in old_by_name:
            added_rows.append(new_row)
            continue
        old_row = old_by_name[name]
        if old_row.status == new_row.status:
            unchanged.append(new_row)
            continue
        old_sev = _SEVERITY.get(old_row.status, 99)
        new_sev = _SEVERITY.get(new_row.status, 99)
        is_regression = new_sev > old_sev
        is_improvement = new_sev < old_sev
        transitions.append(
            Transition(
                name=name,
                old_status=old_row.status,
                new_status=new_row.status,
                is_regression=is_regression,
                is_improvement=is_improvement,
            )
        )

    for name, old_row in old_by_name.items():
        if name not in new_by_name:
            removed_rows.append(old_row)

    return DiffResult(
        transitions=tuple(transitions),
        added_rows=tuple(added_rows),
        removed_rows=tuple(removed_rows),
        unchanged=tuple(unchanged),
    )


def render_text(result: DiffResult) -> str:
    """Human-readable summary suitable for PR-comment paste."""
    lines: list[str] = []
    lines.append("Readiness diff")
    lines.append("==============")
    lines.append("")
    lines.append(f"Unchanged: {len(result.unchanged)}")
    lines.append(f"Improvements: {len(result.improvements)}")
    lines.append(f"Regressions: {len(result.regressions)}")
    lines.append(f"Added rows: {len(result.added_rows)}")
    lines.append(f"Removed rows: {len(result.removed_rows)}")
    lines.append("")

    if result.regressions:
        lines.append("REGRESSIONS")
        lines.append("-----------")
        for t in result.regressions:
            lines.append(t.render())
        lines.append("")

    if result.removed_rows:
        lines.append("REMOVED ROWS (treated as regression)")
        lines.append("------------------------------------")
        for r in result.removed_rows:
            lines.append(f"  - {r.name} (was {r.status})")
        lines.append("")

    if result.improvements:
        lines.append("Improvements")
        lines.append("------------")
        for t in result.improvements:
            lines.append(t.render())
        lines.append("")

    if result.added_rows:
        lines.append("Added rows")
        lines.append("----------")
        for r in result.added_rows:
            lines.append(f"  + {r.name} ({r.status})")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_json(result: DiffResult) -> str:
    """Stable JSON for automation."""
    payload = {
        "summary": {
            "unchanged": len(result.unchanged),
            "improvements": len(result.improvements),
            "regressions": len(result.regressions),
            "added_rows": len(result.added_rows),
            "removed_rows": len(result.removed_rows),
            "has_regressions": result.has_regressions,
        },
        "regressions": [
            {
                "name": t.name,
                "old_status": t.old_status,
                "new_status": t.new_status,
            }
            for t in result.regressions
        ],
        "improvements": [
            {
                "name": t.name,
                "old_status": t.old_status,
                "new_status": t.new_status,
            }
            for t in result.improvements
        ],
        "added_rows": [
            {"name": r.name, "status": r.status} for r in result.added_rows
        ],
        "removed_rows": [
            {"name": r.name, "old_status": r.status} for r in result.removed_rows
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _read_report(path: Path) -> str:
    if not path.is_file():
        print(f"readiness_diff: report not found: {path}", file=sys.stderr)
        sys.exit(2)
    return path.read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Diff two readiness reports. Exit 1 on any regression "
            "(PASS → FAIL/PENDING, removed row, or row whose new status "
            "is worse than its old status). Exit 0 otherwise."
        )
    )
    parser.add_argument(
        "--old",
        required=True,
        type=Path,
        help="Baseline readiness report (markdown).",
    )
    parser.add_argument(
        "--new",
        required=True,
        type=Path,
        help="Current readiness report (markdown).",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    args = parser.parse_args(argv)

    old_text = _read_report(args.old)
    new_text = _read_report(args.new)

    old_rows = parse_report(old_text)
    new_rows = parse_report(new_text)

    if not old_rows:
        print(
            f"readiness_diff: parsed 0 rows from --old {args.old}. "
            "Is this really a readiness report?",
            file=sys.stderr,
        )
        return 2
    if not new_rows:
        print(
            f"readiness_diff: parsed 0 rows from --new {args.new}. "
            "Is this really a readiness report?",
            file=sys.stderr,
        )
        return 2

    result = diff_reports(old_rows, new_rows)

    if args.format == "json":
        sys.stdout.write(render_json(result))
    else:
        sys.stdout.write(render_text(result))

    return 1 if result.has_regressions else 0


if __name__ == "__main__":
    sys.exit(main())
