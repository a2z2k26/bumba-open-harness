"""Mypy baseline ratchet (Sprint S3.1, issue #2340).

Runs ``mypy`` against the configured package(s), compares the resulting
errors against the tracked baseline in ``agent/mypy-baseline.txt``, and
fails on net-new errors. Errors that exist in the baseline are tolerated;
fixed errors are reported as a delta but do not fail the run. Run with
``--update-baseline`` to refresh after intentional debt burndown.

Baseline format:

    Each line is a normalized error key: ``relpath:CODE:message``. The
    line number from mypy's output is intentionally stripped so the
    baseline does not churn when unrelated edits shift line offsets.
    Identical errors (same file + code + message) on different lines
    collapse to a single baseline entry — fixing one fixes both.

Trade-off accepted: a regression that re-introduces the same error on a
different line is treated as already-baselined. The 1.0-cycle priority is
preventing genuinely NEW errors (different message or different file)
without forcing daily baseline rewrites. Future ratchet sprints can tighten
this once the absolute count is down.

Stdlib only. Run from anywhere — the script resolves the repo root
relative to its own location.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


# Repo layout: <repo>/agent/scripts/check_mypy_baseline.py
SCRIPT_PATH = Path(__file__).resolve()
AGENT_ROOT = SCRIPT_PATH.parent.parent
BASELINE_PATH = AGENT_ROOT / "mypy-baseline.txt"
DEFAULT_TARGETS = ("bridge/",)

# Matches: ``path:LINE: error: message  [error-code]``
ERROR_LINE = re.compile(
    r"^(?P<path>[^:]+):(?P<line>\d+):\s*error:\s*(?P<msg>.+?)\s*\[(?P<code>[a-z\-]+)\]\s*$"
)


def normalize(line: str) -> str | None:
    """Strip the line number from a mypy error line.

    Returns a normalized key ``path:code:message`` or ``None`` if the line
    is not an error line (warnings, notes, summary lines).
    """
    match = ERROR_LINE.match(line.rstrip())
    if not match:
        return None
    return f"{match.group('path')}:{match.group('code')}:{match.group('msg')}"


def run_mypy(targets: tuple[str, ...]) -> str:
    """Invoke mypy and return its stdout+stderr as a single string.

    Resolution order for the mypy executable:
      1. ``agent/.venv/bin/mypy`` (developer venv next to ``pyproject.toml``)
      2. ``sys.executable -m mypy`` (running interpreter's mypy module)
      3. bare ``mypy`` (PATH lookup, last resort)

    The Makefile target invokes this via the venv python, so (2) is the
    common path. The CLI fallback supports running the script from a fresh
    shell during local-ci probes.
    """
    venv_mypy = AGENT_ROOT / ".venv" / "bin" / "mypy"
    if venv_mypy.exists():
        cmd = [str(venv_mypy), *targets]
    else:
        cmd = [sys.executable, "-m", "mypy", *targets]
    proc = subprocess.run(
        cmd,
        cwd=AGENT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout + proc.stderr


def collect_errors(mypy_output: str) -> set[str]:
    """Return the set of normalized error keys from mypy's output."""
    keys: set[str] = set()
    for line in mypy_output.splitlines():
        key = normalize(line)
        if key is not None:
            keys.add(key)
    return keys


def load_baseline(path: Path) -> set[str]:
    """Load the tracked baseline. Missing file returns an empty set."""
    if not path.exists():
        return set()
    return {
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }


def write_baseline(path: Path, keys: set[str]) -> None:
    """Write the baseline sorted, with a header comment."""
    header = (
        "# mypy baseline — Sprint S3.1 (#2340)\n"
        "# Format: <path>:<error-code>:<message>\n"
        "# Update via: python agent/scripts/check_mypy_baseline.py --update-baseline\n"
    )
    body = "\n".join(sorted(keys))
    path.write_text(header + body + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Overwrite the baseline with current mypy output (intentional debt burndown).",
    )
    parser.add_argument(
        "--targets",
        nargs="+",
        default=list(DEFAULT_TARGETS),
        help="Mypy targets (default: bridge/).",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=BASELINE_PATH,
        help=f"Baseline file path (default: {BASELINE_PATH.relative_to(AGENT_ROOT.parent)}).",
    )
    args = parser.parse_args(argv)

    output = run_mypy(tuple(args.targets))
    current = collect_errors(output)

    if args.update_baseline:
        write_baseline(args.baseline, current)
        print(f"Baseline updated: {len(current)} errors tracked at {args.baseline}")
        return 0

    baseline = load_baseline(args.baseline)
    if not baseline:
        print(
            f"ERROR: baseline file not found at {args.baseline}. "
            "Run with --update-baseline to create it.",
            file=sys.stderr,
        )
        return 2

    new_errors = current - baseline
    fixed_errors = baseline - current

    if fixed_errors:
        print(f"Progress: {len(fixed_errors)} error(s) no longer in baseline:")
        for key in sorted(fixed_errors):
            print(f"  - {key}")
        print(
            "  → Run with --update-baseline to shrink the tracked baseline.",
            flush=True,
        )

    if new_errors:
        print(
            f"\nFAIL: {len(new_errors)} new mypy error(s) not in baseline:",
            file=sys.stderr,
        )
        for key in sorted(new_errors):
            print(f"  + {key}", file=sys.stderr)
        print(
            f"\nBaseline has {len(baseline)} tracked errors. "
            f"Current run has {len(current)} errors.",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK: no net-new mypy errors. Baseline: {len(baseline)} | Current: {len(current)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
