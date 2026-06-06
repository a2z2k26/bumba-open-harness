"""QA department tool functions."""

from __future__ import annotations

import logging

from pydantic_ai import RunContext

from teams._types import BridgeDeps
from teams.tools._common import _run_subprocess

log = logging.getLogger(__name__)


async def run_tests(ctx: RunContext[BridgeDeps], path: str = "tests/") -> str:
    """Run pytest against the given path. Returns the test output."""
    output, code = await _run_subprocess(
        ["python", "-m", "pytest", path, "-v", "--tb=short"],
        timeout=180,
    )
    status = "PASSED" if code == 0 else f"FAILED (exit {code})"
    return f"{status}\n\n{output[-4000:]}"


async def coverage_report(
    ctx: RunContext[BridgeDeps], module: str = ""
) -> str:
    """Generate a pytest coverage report."""
    cmd = [
        "python", "-m", "pytest",
        "--cov=" + (module or "."),
        "--cov-report=term-missing",
        "-q",
    ]
    output, _code = await _run_subprocess(cmd, timeout=240)
    return output[-4000:]


async def security_scan(
    ctx: RunContext[BridgeDeps], path: str = "."
) -> str:
    """Run bandit security scan against the given path."""
    output, code = await _run_subprocess(
        ["bandit", "-r", path, "-f", "txt"],
        timeout=120,
    )
    return f"Exit code: {code}\n\n{output[-3000:]}"
