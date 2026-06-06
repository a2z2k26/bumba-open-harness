"""Append a Plan-02-format ledger row to agent/data/experiments.md.

Used by Chain F (#987 / #1000 / #1008) of the operator-gated runbook —
the three multi-day shadow soaks each need a daily summary row in the
shared ``experiments.md`` ledger. This helper standardises the format.

Plan 02 ledger format (from existing experiments.md):

    ## [YYYY-MM-DD HH:MM] iter-XXXX | <status> | <one-line summary>

    <optional body, 1-3 sentences>

Extended for shadow soaks:

  - status options: ``shadow``, ``flip-on``, ``flip-off``, ``extend``,
    ``green``, ``red``, ``rollback``
  - feature tag: passed via --feature; encoded in the iter slug for filtering
    later (iter-{feature}-{date}; e.g. iter-board-v2-2026-05-09)

Usage:

  # Daily shadow row for #987 (evolution loop)
  python -m scripts.shadow_soak_append \\
      --feature evolution-loop \\
      --status shadow \\
      --note "30 iters today, fitness +0.4%, 2 spot-checks accepted"

  # Decision row for #1000 (memory v2 disclosure)
  python -m scripts.shadow_soak_append \\
      --feature memory-v2-disclosure \\
      --status flip-on \\
      --note "Day-14 verdict: green; cost neutral; flag flipped via PR #XXXX"

Stdlib only.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LEDGER = Path("/opt/bumba-harness/agent-flat/agent/data/experiments.md")

VALID_STATUSES = {
    "shadow",
    "flip-on",
    "flip-off",
    "extend",
    "green",
    "red",
    "rollback",
    "keep",  # mirrors the existing experiment_loop status vocabulary
    "discard",
}


def render_row(
    feature: str,
    status: str,
    note: str,
    timestamp: datetime,
    body: str = "",
) -> str:
    """Build a single Plan-02-format ledger entry."""
    iter_slug = f"iter-{feature}-{timestamp.strftime('%Y%m%d')}"
    header = (
        f"## [{timestamp.strftime('%Y-%m-%d %H:%M')}] {iter_slug} "
        f"| {status} | {note}"
    )
    parts = [header, ""]
    if body:
        parts.append(body.strip())
        parts.append("")
    return "\n".join(parts) + "\n"


def append_to_ledger(ledger: Path, row: str) -> None:
    """Append the row to ledger; create the file if missing (with no header)."""
    ledger.parent.mkdir(parents=True, exist_ok=True)
    if not ledger.exists():
        ledger.write_text("", encoding="utf-8")
    with ledger.open("a", encoding="utf-8") as fh:
        # Ensure separation from prior entry
        existing = ledger.read_text(encoding="utf-8")
        if existing and not existing.endswith("\n\n"):
            fh.write("\n" if existing.endswith("\n") else "\n\n")
        fh.write(row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--feature",
        required=True,
        help="Feature slug (e.g. board-v2, memory-v2-disclosure, evolution-loop)",
    )
    parser.add_argument(
        "--status",
        required=True,
        choices=sorted(VALID_STATUSES),
        help="One of: " + ", ".join(sorted(VALID_STATUSES)),
    )
    parser.add_argument(
        "--note",
        required=True,
        help="One-line summary (≤120 chars recommended)",
    )
    parser.add_argument(
        "--body",
        default="",
        help="Optional 1-3 sentence body for context",
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=DEFAULT_LEDGER,
        help=f"Path to experiments.md (default: {DEFAULT_LEDGER})",
    )
    parser.add_argument(
        "--timestamp",
        help="Override timestamp (ISO-8601 UTC); default: now()",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the row without appending",
    )
    args = parser.parse_args(argv)

    if args.timestamp:
        try:
            ts = datetime.fromisoformat(args.timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            print(f"ERROR: bad --timestamp: {exc}", file=sys.stderr)
            return 2
    else:
        ts = datetime.now(timezone.utc)

    if len(args.note) > 200:
        print(
            "WARNING: --note > 200 chars; consider moving detail to --body",
            file=sys.stderr,
        )

    row = render_row(args.feature, args.status, args.note, ts, args.body)

    if args.dry_run:
        print("--- DRY RUN — would append ---")
        print(row)
        return 0

    append_to_ledger(args.ledger, row)
    print(f"Appended to {args.ledger}: {args.feature} | {args.status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
