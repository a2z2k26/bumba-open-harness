"""Test that SKIP results do not double-record via record_success.

FR-007 regression: runner.py unconditionally called record_success() even
when service returned a SKIP result.  This bumped total_runs and overwrote
last_run, making telemetry report inflated run counts.
"""
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent


def test_skip_does_not_call_record_success():
    """When runner gets a SKIP result, it must not call record_success."""
    runner_src = (_REPO_ROOT / "agent/bridge/services/runner.py").read_text()

    # The fix must branch on skip_reason before calling record_success
    assert "skip_reason" in runner_src, "runner.py must check skip_reason"

    lines = runner_src.splitlines()

    # Find actual record_success *call* lines — exclude comments and def lines
    record_success_call_lines = [
        i for i, line in enumerate(lines)
        if "record_success" in line
        and "def " not in line
        and not line.lstrip().startswith("#")
    ]
    # Find actual skip_reason check lines — exclude comments
    skip_reason_lines = [
        i for i, line in enumerate(lines)
        if "skip_reason" in line
        and not line.lstrip().startswith("#")
    ]

    assert record_success_call_lines, "record_success call not found in runner.py"
    assert skip_reason_lines, "skip_reason check not found in runner.py"

    # The skip_reason check must appear BEFORE the record_success call
    first_skip_check = min(skip_reason_lines)
    first_record_success = min(record_success_call_lines)
    assert first_skip_check < first_record_success, (
        f"skip_reason check (line {first_skip_check}) must precede "
        f"record_success call (line {first_record_success})"
    )


def test_record_success_guarded_by_elif():
    """record_success must be inside an elif branch, not bare if."""
    runner_src = (_REPO_ROOT / "agent/bridge/services/runner.py").read_text()
    lines = runner_src.splitlines()

    # Find the line with elif hasattr(svc, "record_success")
    elif_lines = [
        i for i, line in enumerate(lines)
        if "elif hasattr(svc" in line and "record_success" in line
    ]
    assert elif_lines, (
        "runner.py must use 'elif hasattr(svc, \"record_success\")' "
        "(not bare 'if') to guard the record_success call after skip_reason check"
    )


def test_skip_reason_check_immediately_precedes_elif():
    """The skip_reason branch and the elif record_success must be adjacent."""
    runner_src = (_REPO_ROOT / "agent/bridge/services/runner.py").read_text()
    lines = runner_src.splitlines()

    # Locate the skip_reason is not None guard line
    skip_guard_lines = [
        i for i, line in enumerate(lines)
        if "skip_reason is not None" in line
    ]
    elif_success_lines = [
        i for i, line in enumerate(lines)
        if "elif hasattr(svc" in line and "record_success" in line
    ]

    assert skip_guard_lines, "skip_reason is not None check not found"
    assert elif_success_lines, "elif record_success guard not found"

    # They should be within a few lines of each other (pass + comment between them)
    closest_gap = min(
        abs(e - s)
        for s in skip_guard_lines
        for e in elif_success_lines
    )
    assert closest_gap <= 5, (
        f"skip_reason guard and elif record_success are {closest_gap} lines apart — "
        "expected them to be adjacent (within 5 lines)"
    )
