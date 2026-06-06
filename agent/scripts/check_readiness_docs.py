"""Verify readiness docs agree with the readiness.sh harness.

Sprint R6.2 (current-state improvement plan) — pragmatic tripwire that
catches one specific drift: ``agent/scripts/readiness.sh`` says a row
is live but ``docs/operator/readiness-runbook.md`` still has it in the
PENDING table (or vice-versa).

The check is intentionally narrow — not a generic natural-language
verifier. It only enforces:

1. Every ``run_check`` row in ``readiness.sh`` has an entry in the
   live-checks table at the top of the runbook.
2. Every ``stub_pending`` row in ``readiness.sh`` has an entry in the
   PENDING-rows table of the runbook (or has the historical "RETIRED"
   marker if the row was retired by R1.x).
3. No row in the runbook's PENDING table corresponds to a row that's
   ALSO live in ``readiness.sh`` (the stale-doc case).

Sprint backend-op S5.2 extends the script with **backend doc drift
patterns** that S5.1 brought into alignment. Each pattern is a single
literal-string match (or absence-of-marker) — no NL parsing. The checks
fail loud when a future doc edit reintroduces a stale claim:

- ``docs/current-state`` and ``docs/operator`` must not contain
  ``agent-flat/agent/mcp-servers/bumba-memory/mcp-server.js`` (the
  legacy warm MCP path — the warm bumba-memory MCP now lives at
  ``mcp-servers/bumba-memory/dist/index.js``).
- ``docs/current-state`` must not contain raw ``8199`` unless the doc
  also contains ``historical`` or ``stale`` (the bridge has been on
  ``8200`` since D6-bis on 2026-05-09).
- ``docs/current-state/README.md`` must mention
  ``feature_flags.yaml`` — the source-of-truth feature-flag inventory.

Usage
-----
::

    cd /home/operator/bumba-open-harness
    python3 agent/scripts/check_readiness_docs.py

Exit codes
----------
- ``0`` — readiness docs agree with the script.
- ``1`` — at least one drift detected.
- ``2`` — internal harness error (file missing, parse failed, etc.).
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_READINESS_SH = _REPO_ROOT / "agent" / "scripts" / "readiness.sh"
_RUNBOOK = _REPO_ROOT / "docs" / "operator" / "readiness-runbook.md"

# ---------------------------------------------------------------------------
# Backend doc drift patterns (Sprint backend-op S5.2, issue #2287)
# ---------------------------------------------------------------------------

# Legacy warm-MCP path. The warm bumba-memory MCP server has not lived at
# this path since the dist/ relocation; any doc reintroducing it is stale.
_LEGACY_WARM_MCP_PATH = (
    "agent-flat/agent/mcp-servers/bumba-memory/mcp-server.js"
)

# Pre-D6-bis API port. The bridge has been on 8200 since 2026-05-09. Any
# raw occurrence in current-state docs is stale unless the surrounding doc
# qualifies it as historical (``historical`` or ``stale`` anywhere in the
# file body).
_LEGACY_API_PORT = "8199"
_PORT_QUALIFIERS = ("historical", "stale")

# README.md in current-state must mention the feature-flag YAML, which is
# the operator-facing source of truth for feature flags.
_FEATURE_FLAGS_YAML_MARKER = "feature_flags.yaml"

# Match `run_check "name" \`, `stub_pending "name" \`, and the
# `record_row "name" "PASS"` form readiness.sh uses for the one custom
# subshell block (services.runner --validate at line ~128).
_RUN_CHECK_RE = re.compile(r'^\s*run_check\s+"([^"]+)"')
_STUB_PENDING_RE = re.compile(r'^\s*stub_pending\s+"([^"]+)"')
_RECORD_ROW_PASS_RE = re.compile(
    r'^\s*record_row\s+"([^"]+)"\s+"PASS"'
)
_RECORD_ROW_FAIL_RE = re.compile(
    r'^\s*record_row\s+"([^"]+)"\s+"FAIL"'
)

# Match the live-checks table introduced by R6.2:
#     | N | `Row name` | <command> | <source> |
# Captures the first backticked cell after the index column.
_LIVE_TABLE_ROW_RE = re.compile(
    r"^\|\s*(?P<num>\d+)\s*\|\s*[`](?P<name>[^`]+)[`]\s*\|"
)
# PENDING-rows table:  | ~~`name`~~ | blocker | swap-in |
# (or unstrikethrough if the row is currently active)
_PENDING_TABLE_ROW_RE = re.compile(
    r"^\|\s*(?P<marker>~~)?[`](?P<name>[^|`]+?)[`](?P=marker)?\s*\|"
)


@dataclass
class HarnessRows:
    """What ``readiness.sh`` declares."""

    live: set[str] = field(default_factory=set)
    pending: set[str] = field(default_factory=set)


@dataclass
class RunbookRows:
    """What the runbook declares."""

    live: set[str] = field(default_factory=set)
    pending_active: set[str] = field(default_factory=set)
    pending_retired: set[str] = field(default_factory=set)


@dataclass
class CheckResult:
    """Outcome of one check pass."""

    harness: HarnessRows = field(default_factory=HarnessRows)
    runbook: RunbookRows = field(default_factory=RunbookRows)
    stale_doc_pending: list[str] = field(default_factory=list)
    """Rows the runbook says PENDING but readiness.sh has live."""
    undocumented_pending: list[str] = field(default_factory=list)
    """Rows readiness.sh has stub_pending but the runbook doesn't list."""
    undocumented_live: list[str] = field(default_factory=list)
    """Rows readiness.sh has live but the runbook doesn't list."""
    backend_doc_drift: list[str] = field(default_factory=list)
    """Stale backend-doc claims (legacy ports, MCP paths, missing markers)."""

    @property
    def ok(self) -> bool:
        return not (
            self.stale_doc_pending
            or self.undocumented_pending
            or self.undocumented_live
            or self.backend_doc_drift
        )


def parse_readiness_sh(text: str) -> HarnessRows:
    """Extract live + pending row names from readiness.sh.

    Three call shapes count as a "live" row: ``run_check "name" ...``,
    ``record_row "name" "PASS" ...``, and ``record_row "name" "FAIL" ...``.
    The PASS/FAIL forms cover custom subshell blocks (e.g. the
    services.runner --validate block at ~line 128) that don't go through
    ``run_check`` but still emit a real row.
    """
    rows = HarnessRows()
    for line in text.splitlines():
        m = _RUN_CHECK_RE.match(line)
        if m:
            name = m.group(1).strip()
            if not _is_shell_variable(name):
                rows.live.add(name)
            continue
        m = _STUB_PENDING_RE.match(line)
        if m:
            name = m.group(1).strip()
            if not _is_shell_variable(name):
                rows.pending.add(name)
            continue
        m = _RECORD_ROW_PASS_RE.match(line)
        if m:
            name = m.group(1).strip()
            if not _is_shell_variable(name):
                rows.live.add(name)
            continue
        m = _RECORD_ROW_FAIL_RE.match(line)
        if m:
            # FAIL is also a live row (the gate failed; the row exists).
            name = m.group(1).strip()
            if not _is_shell_variable(name):
                rows.live.add(name)
    return rows


def _is_shell_variable(name: str) -> bool:
    """True if the captured name is a shell variable (e.g. ``${name}``).

    Filters out helper-function definitions whose first arg is the
    literal name placeholder rather than a real row label.
    """
    return name.startswith("$") or "${" in name


def parse_runbook(text: str) -> RunbookRows:
    """Extract live + pending row names from the runbook.

    Three sections matter:

    - The "live checks" table at the top of the runbook (`## The N live checks`
      or similar). Rows have shape `| N | name | source |`.
    - The "PENDING rows" table. Rows have shape ``| `name` | blocker | swap-in |``.
      Strikethrough (``~~`name`~~``) marks RETIRED rows.
    """
    rows = RunbookRows()
    section: str | None = None  # "live", "pending", or None
    for raw_line in text.splitlines():
        stripped = raw_line.rstrip()
        if stripped.startswith("## "):
            heading = stripped[3:].lower()
            if "live check" in heading:
                section = "live"
            elif "pending row" in heading:
                section = "pending"
            else:
                section = None
            continue
        if section == "live":
            m = _LIVE_TABLE_ROW_RE.match(raw_line)
            if not m:
                continue
            name = m.group("name").strip()
            if name:
                rows.live.add(name)
        elif section == "pending":
            m = _PENDING_TABLE_ROW_RE.match(raw_line)
            if not m:
                continue
            name = m.group("name").strip()
            # Skip header row literal.
            if name == "PENDING row":
                continue
            if m.group("marker"):
                rows.pending_retired.add(name)
            else:
                rows.pending_active.add(name)
    return rows


def check(harness: HarnessRows, runbook: RunbookRows) -> CheckResult:
    """Compare harness and runbook; populate drift lists."""
    result = CheckResult(harness=harness, runbook=runbook)

    # 1. Stale doc pending: runbook says ACTIVE pending but harness has live.
    for name in sorted(runbook.pending_active):
        if name in harness.live:
            result.stale_doc_pending.append(name)

    # 2. Undocumented pending: harness has stub_pending but runbook lists
    #    neither in active nor retired.
    runbook_pending_all = runbook.pending_active | runbook.pending_retired
    for name in sorted(harness.pending):
        if name not in runbook_pending_all:
            result.undocumented_pending.append(name)

    # 3. Undocumented live: harness has run_check but runbook live table
    #    doesn't list the row. Best-effort name-match (the runbook's
    #    table column is the "Check" name; the harness's row is what's
    #    in the run_check first arg). The two should match exactly.
    for name in sorted(harness.live):
        if name not in runbook.live:
            result.undocumented_live.append(name)

    return result


def find_stale_backend_doc_patterns(root: Path) -> list[str]:
    """Return a list of stale-claim drift messages found under ``root``.

    Scans ``docs/current-state`` and ``docs/operator`` for the literal
    patterns S5.1 cleaned up. Each returned string is of the form
    ``<path>: <reason>`` and is printable as-is.

    Empty list = no drift detected.
    """
    failures: list[str] = []

    # 1. Legacy warm MCP path — banned outright in both trees.
    for subdir in ("docs/current-state", "docs/operator"):
        base = root / subdir
        if not base.is_dir():
            continue
        for doc in sorted(base.rglob("*.md")):
            try:
                text = doc.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                # If we can't read the file we can't audit it; skip
                # quietly — the readiness gate is intentionally
                # best-effort for this drift class.
                continue
            if _LEGACY_WARM_MCP_PATH in text:
                failures.append(f"{doc}: legacy warm MCP path")

    # 2. Unqualified legacy port 8199 in current-state only. Operator
    #    runbooks are allowed to discuss the historical port without
    #    qualifiers (they're operator-facing release notes); current-state
    #    docs are the authoritative live snapshot and must mark stale.
    current_state = root / "docs/current-state"
    if current_state.is_dir():
        for doc in sorted(current_state.rglob("*.md")):
            try:
                text = doc.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if _LEGACY_API_PORT not in text:
                continue
            lowered = text.lower()
            if any(q in lowered for q in _PORT_QUALIFIERS):
                continue
            failures.append(f"{doc}: unqualified legacy port {_LEGACY_API_PORT}")

    # 3. current-state/README.md must mention feature_flags.yaml.
    readme = root / "docs/current-state" / "README.md"
    if readme.is_file():
        try:
            text = readme.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        if _FEATURE_FLAGS_YAML_MARKER not in text:
            failures.append(
                f"{readme}: missing required reference to "
                f"{_FEATURE_FLAGS_YAML_MARKER}"
            )

    return failures


def render_text(result: CheckResult) -> str:
    lines = [
        "Readiness docs check",
        f"  harness.live:           {len(result.harness.live)}",
        f"  harness.pending:        {len(result.harness.pending)}",
        f"  runbook.live:           {len(result.runbook.live)}",
        f"  runbook.pending_active: {len(result.runbook.pending_active)}",
        f"  runbook.pending_retired:{len(result.runbook.pending_retired)}",
        "",
    ]
    if result.stale_doc_pending:
        lines.append("STALE DOC PENDING (runbook says PENDING but harness has live):")
        for name in result.stale_doc_pending:
            lines.append(f"  - {name}")
        lines.append("")
    if result.undocumented_pending:
        lines.append("UNDOCUMENTED PENDING (harness stub_pending but runbook doesn't list):")
        for name in result.undocumented_pending:
            lines.append(f"  - {name}")
        lines.append("")
    if result.undocumented_live:
        lines.append("UNDOCUMENTED LIVE (harness run_check but runbook doesn't list):")
        for name in result.undocumented_live:
            lines.append(f"  - {name}")
        lines.append("")
    if result.backend_doc_drift:
        lines.append(
            "BACKEND DOC DRIFT (current-state/operator docs reintroduced "
            "a stale claim):"
        )
        for msg in result.backend_doc_drift:
            lines.append(f"  - {msg}")
        lines.append("")
    if result.ok:
        lines.append("OK — readiness docs agree with the harness.")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify docs/operator/readiness-runbook.md agrees with "
            "agent/scripts/readiness.sh. Catches stale-doc PENDING + "
            "undocumented stub_pending + undocumented run_check rows."
        )
    )
    parser.add_argument(
        "--readiness-sh",
        default=str(_READINESS_SH),
        help=f"Path to readiness.sh (default: {_READINESS_SH}).",
    )
    parser.add_argument(
        "--runbook",
        default=str(_RUNBOOK),
        help=f"Path to readiness-runbook.md (default: {_RUNBOOK}).",
    )
    parser.add_argument(
        "--repo-root",
        default=str(_REPO_ROOT),
        help=(
            "Repo root used to resolve docs/current-state and docs/operator "
            f"for backend doc drift checks (default: {_REPO_ROOT})."
        ),
    )
    args = parser.parse_args(argv)

    sh_path = Path(args.readiness_sh)
    runbook_path = Path(args.runbook)
    repo_root = Path(args.repo_root)

    if not sh_path.is_file():
        print(f"check_readiness_docs: readiness.sh not found: {sh_path}", file=sys.stderr)
        return 2
    if not runbook_path.is_file():
        print(f"check_readiness_docs: runbook not found: {runbook_path}", file=sys.stderr)
        return 2

    try:
        harness = parse_readiness_sh(sh_path.read_text(encoding="utf-8"))
        runbook = parse_runbook(runbook_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(
            f"check_readiness_docs: parse error: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2

    result = check(harness, runbook)
    # S5.2: layer backend doc drift on top of the row drift check. The
    # repo-root resolution is independent of the readiness.sh / runbook
    # paths so the check still runs even when --readiness-sh / --runbook
    # are pointed at fixtures.
    result.backend_doc_drift = find_stale_backend_doc_patterns(repo_root)

    sys.stdout.write(render_text(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
