"""ResourceWarning baseline ratchet (Sprint S6.1, issue #2351).

Runs the offline pytest lane with ``-W default::ResourceWarning`` and
diffs the resulting warning set against
``agent/resource-warning-baseline.txt``. Fails on net-new warnings;
flat or shrinking passes. Use ``--update-baseline`` after debt
burndown. Sibling of ``check_mypy_baseline.py`` (S3.1, #2340).
Policy: ``docs/testing/resource-warnings.md``. Stdlib only.

Baseline keys: ``<test_nodeid>|<warning_kind>`` with memory addresses
and pytest tmp paths normalized. Repeat warnings from the same test
collapse to one entry.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


# Repo layout: <repo>/agent/scripts/check_resource_warning_baseline.py
SCRIPT_PATH = Path(__file__).resolve()
AGENT_ROOT = SCRIPT_PATH.parent.parent
BASELINE_PATH = AGENT_ROOT / "resource-warning-baseline.txt"

# Pytest emits warnings as two-line blocks:
#   tests/test_foo.py::TestBar::test_baz
#     /abs/path/lib.py:LINE: ResourceWarning: unclosed database in <sqlite3.Connection object at 0x123>
# The first line is the test nodeid; the second carries the warning text.
TEST_NODEID = re.compile(r"^(?P<nodeid>[^\s]+\.py::[^\s]+)\s*$")
WARNING_LINE = re.compile(
    r"^\s+(?P<path>[^:]+):(?P<line>\d+):\s*ResourceWarning:\s*(?P<msg>.+?)\s*$"
)

# Volatile fragments in warning messages — must be normalized so the
# baseline is stable across runs. Keep the regex set small and obvious.
ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]+")
PYTEST_TMP_RE = re.compile(
    r"/(?:private/)?(?:var|tmp)/[^']*pytest-of-[^/]+/pytest-\d+/[^']*"
)
PID_DIR_RE = re.compile(r"/pytest-\d+/")
# S6.2 (#2352) — also normalize random temp-file suffixes outside pytest-of-*
# trees. tempfile.NamedTemporaryFile prefixed paths (e.g. bumba_img_xxxxxx.png,
# bumba-agent-tools/mcp-xxxxxxxx.json) carry random suffixes that would
# otherwise re-attribute the same logical leak as a "new" warning each run.
TEMPFILE_SUFFIX_RES = (
    # /var/folders/.../T/bumba_img_<random>.<ext>  (discord image downloads)
    re.compile(r"(/T/bumba_img_)[A-Za-z0-9_]+(\.[a-z]+)"),
    # /var/folders/.../T/bumba-agent-tools/mcp-<random>.json  (tool isolation)
    re.compile(r"(/T/bumba-agent-tools/mcp-)[A-Za-z0-9]+(\.json)"),
)


def normalize_kind(msg: str) -> str:
    """Strip memory addresses + pytest tmp paths from a warning message."""
    out = ADDRESS_RE.sub("<ADDR>", msg)
    out = PYTEST_TMP_RE.sub("<PYTEST_TMP>", out)
    out = PID_DIR_RE.sub("/<PYTEST_TMP>/", out)
    for pattern in TEMPFILE_SUFFIX_RES:
        out = pattern.sub(r"\1<RAND>\2", out)
    return out.strip()


def parse_warnings(pytest_output: str) -> set[str]:
    """Return ``{<nodeid>|<kind>}`` set from pytest's warning summary."""
    keys: set[str] = set()
    current_nodeid = "<session>"
    for line in pytest_output.splitlines():
        nid = TEST_NODEID.match(line)
        if nid:
            current_nodeid = nid.group("nodeid")
            continue
        wmatch = WARNING_LINE.match(line)
        if wmatch:
            keys.add(f"{current_nodeid}|{normalize_kind(wmatch.group('msg'))}")
    return keys


def run_pytest(extra_args: tuple[str, ...]) -> str:
    """Invoke the offline pytest lane with ResourceWarning surfacing."""
    venv_python = AGENT_ROOT / ".venv" / "bin" / "python"
    interpreter = str(venv_python) if venv_python.exists() else sys.executable
    cmd = [
        interpreter, "-m", "pytest",
        "tests/", "job_search/tests/",
        "-m", "not live and not socket",
        "-q", "-W", "default::ResourceWarning",
        "-p", "no:cacheprovider", "--no-header",
        *extra_args,
    ]
    proc = subprocess.run(cmd, cwd=AGENT_ROOT, capture_output=True, text=True, check=False)
    return proc.stdout + proc.stderr


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
        "# ResourceWarning baseline — Sprint S6.1 (#2351)\n"
        "# Format: <test_nodeid>|<warning_kind>\n"
        "# Memory addresses, pytest tmp paths, and PID dirs are normalized.\n"
        "# Update via: python agent/scripts/check_resource_warning_baseline.py --update-baseline\n"
    )
    body = "\n".join(sorted(keys))
    path.write_text(header + body + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Overwrite the baseline with current pytest output (intentional debt burndown).",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=BASELINE_PATH,
        help=f"Baseline file path (default: {BASELINE_PATH.relative_to(AGENT_ROOT.parent)}).",
    )
    parser.add_argument(
        "--from-log",
        type=Path,
        default=None,
        help="Read pytest output from a file instead of running pytest (for fast iteration).",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Extra args forwarded to pytest (after --).",
    )
    args = parser.parse_args(argv)

    if args.from_log:
        output = args.from_log.read_text(encoding="utf-8")
    else:
        extras = tuple(a for a in args.pytest_args if a != "--")
        output = run_pytest(extras)

    current = parse_warnings(output)

    if args.update_baseline:
        write_baseline(args.baseline, current)
        print(
            f"Baseline updated: {len(current)} ResourceWarning(s) tracked at {args.baseline}"
        )
        return 0

    baseline = load_baseline(args.baseline)
    if not baseline:
        print(
            f"ERROR: baseline file not found at {args.baseline}. "
            "Run with --update-baseline to create it.",
            file=sys.stderr,
        )
        return 2

    new_warnings = current - baseline
    fixed_warnings = baseline - current

    if fixed_warnings:
        print(f"Progress: {len(fixed_warnings)} warning(s) no longer in baseline:")
        for key in sorted(fixed_warnings):
            print(f"  - {key}")
        print(
            "  → Run with --update-baseline to shrink the tracked baseline.",
            flush=True,
        )

    if new_warnings:
        print(
            f"\nFAIL: {len(new_warnings)} new ResourceWarning(s) not in baseline:",
            file=sys.stderr,
        )
        for key in sorted(new_warnings):
            print(f"  + {key}", file=sys.stderr)
        print(
            f"\nBaseline has {len(baseline)} tracked warnings. "
            f"Current run has {len(current)} warnings.",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK: no net-new ResourceWarnings. "
        f"Baseline: {len(baseline)} | Current: {len(current)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
