"""Ruff + mypy backpressure gates for the experiment loop (Sprint 02.07b).

Spec: docs/specs/2026-04-25-reference-audit/spec-02-07b-add-ruff-mypy-backpressure-gates-after-pytest.md
Issue: #982

After pytest passes, the experiment loop runs lint + typecheck against the
*changed files only* so that an iteration which keeps the test suite green
but introduces new ruff warnings or mypy errors is *discarded*. Without
this gate, code-quality regressions can sneak in any time the change
happens not to break a test.

Module is intentionally standalone (no imports from ``experiment_loop``)
so the gate logic can be unit-tested in isolation. ``run_quality_gates``
is the single public entry point; the loop calls it after the pytest
gate passes.

The gate is *strict-on-changes*: every changed file must pass ruff and
mypy with zero issues. The spec leaves room for a future "delta vs
baseline" mode (only fail on *new* warnings), but Sprint 02.07b ships
the simpler binary gate — anything cleaner can come once the gate is
known to work in production.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# Public type aliases — useful for callers that want to annotate their
# own collections of GateResult.
GateOutcome = Literal["pass", "fail"]
GateName = Literal["ruff", "mypy"]

# Default per-gate timeouts. Ruff is fast; mypy on a single file can be
# surprisingly slow because it imports the world. Both are caller-overridable.
DEFAULT_RUFF_TIMEOUT_S = 60
DEFAULT_MYPY_TIMEOUT_S = 120


@dataclass(frozen=True)
class GateResult:
    """One quality gate's verdict.

    Frozen so callers MUST treat instances as immutable — construct a new
    ``GateResult`` rather than mutating fields. ``summary`` is a short
    human-readable reason on failure (e.g. ``"ruff: 5 issue(s)"``); empty
    on pass. Full ``stdout`` / ``stderr`` are captured for the
    experiment-log notes so the operator can inspect the actual
    diagnostics post-hoc without re-running the gate.
    """

    name: GateName
    outcome: GateOutcome
    summary: str
    stdout: str
    stderr: str
    duration_seconds: float


def _run_subprocess(
    cmd: list[str],
    *,
    cwd: Path | None,
    timeout_s: int,
) -> tuple[int, str, str]:
    """Run ``cmd`` and return ``(exit_code, stdout, stderr)``.

    ``cwd`` is the working directory for the subprocess. ``None`` means
    "inherit", which is fine for absolute paths in ``cmd``. Raises
    ``subprocess.TimeoutExpired`` to the caller, which converts that
    into a structured ``GateResult`` rather than letting the loop crash.
    """
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _make_pass(name: GateName, *, duration_seconds: float = 0.0) -> GateResult:
    """Construct a vacuous-pass ``GateResult`` for the empty-changed-files case."""
    return GateResult(
        name=name,
        outcome="pass",
        summary="",
        stdout="",
        stderr="",
        duration_seconds=duration_seconds,
    )


def _make_timeout(name: GateName, timeout_s: int, *, duration_seconds: float) -> GateResult:
    """Construct a ``fail`` ``GateResult`` for a timeout.

    Timeouts are treated as failures rather than crashes so the loop
    discards the iteration cleanly — a gate that can't decide in
    ``timeout_s`` seconds is unsafe to merge.
    """
    return GateResult(
        name=name,
        outcome="fail",
        summary=f"{name}: timed out after {timeout_s}s",
        stdout="",
        stderr=f"timeout after {timeout_s}s",
        duration_seconds=duration_seconds,
    )


def _filter_python_files(changed_files: list[Path]) -> list[Path]:
    """Return only ``.py`` files; ruff/mypy don't apply to other types.

    The spec gates on *Python* lint + typecheck regressions, so non-Python
    edits (e.g. Markdown, TOML) are vacuously fine here.
    """
    return [p for p in changed_files if p.suffix == ".py"]


def run_ruff_gate(
    changed_files: list[Path],
    *,
    cwd: Path | None = None,
    timeout_s: int = DEFAULT_RUFF_TIMEOUT_S,
) -> GateResult:
    """Run ``ruff check`` on ``changed_files``. Empty input → vacuous pass.

    Uses ``python -m ruff check`` so the gate works with any Python entry
    point that has ruff installed (worktree venv, system Python, or
    ``uv tool run``-injected env). Exit 0 means clean; non-zero means
    one or more issues — the gate fails regardless of count.
    """
    py_files = _filter_python_files(changed_files)
    if not py_files:
        return _make_pass("ruff")

    start = time.time()
    cmd = [sys.executable, "-m", "ruff", "check", *[str(p) for p in py_files]]
    try:
        exit_code, stdout, stderr = _run_subprocess(cmd, cwd=cwd, timeout_s=timeout_s)
    except subprocess.TimeoutExpired:
        return _make_timeout("ruff", timeout_s, duration_seconds=time.time() - start)

    duration = time.time() - start
    if exit_code == 0:
        return GateResult(
            name="ruff",
            outcome="pass",
            summary="",
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
        )

    # Best-effort summary: count lines mentioning "error"-style markers.
    # Ruff prints ``path:line:col: CODE message`` per issue, so the line
    # count is a reasonable proxy. Fall back to "1+ issue" when stdout is
    # empty (e.g. config error printed to stderr only).
    issue_lines = [ln for ln in stdout.splitlines() if ln.strip()]
    issue_count = len(issue_lines) if issue_lines else 1
    return GateResult(
        name="ruff",
        outcome="fail",
        summary=f"ruff: {issue_count} issue(s)",
        stdout=stdout,
        stderr=stderr,
        duration_seconds=duration,
    )


def run_mypy_gate(
    changed_files: list[Path],
    *,
    cwd: Path | None = None,
    timeout_s: int = DEFAULT_MYPY_TIMEOUT_S,
) -> GateResult:
    """Run ``mypy`` on ``changed_files``. Empty input → vacuous pass.

    Like ``run_ruff_gate``, this uses ``python -m mypy`` for portability.
    Exit 0 means clean; any other exit means one or more type errors.
    Mypy's ``--no-error-summary`` keeps stdout focused on the issues
    themselves so the summary string stays informative.
    """
    py_files = _filter_python_files(changed_files)
    if not py_files:
        return _make_pass("mypy")

    start = time.time()
    cmd = [
        sys.executable,
        "-m",
        "mypy",
        "--no-error-summary",
        *[str(p) for p in py_files],
    ]
    try:
        exit_code, stdout, stderr = _run_subprocess(cmd, cwd=cwd, timeout_s=timeout_s)
    except subprocess.TimeoutExpired:
        return _make_timeout("mypy", timeout_s, duration_seconds=time.time() - start)

    duration = time.time() - start
    if exit_code == 0:
        return GateResult(
            name="mypy",
            outcome="pass",
            summary="",
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
        )

    # Mypy prints ``path:line: error: message`` per issue — count those.
    error_lines = [ln for ln in stdout.splitlines() if ": error:" in ln]
    error_count = len(error_lines) if error_lines else 1
    return GateResult(
        name="mypy",
        outcome="fail",
        summary=f"mypy: {error_count} error(s)",
        stdout=stdout,
        stderr=stderr,
        duration_seconds=duration,
    )


def run_quality_gates(
    changed_files: list[Path],
    *,
    cwd: Path | None = None,
    ruff_timeout_s: int = DEFAULT_RUFF_TIMEOUT_S,
    mypy_timeout_s: int = DEFAULT_MYPY_TIMEOUT_S,
) -> tuple[GateResult, ...]:
    """Run ruff then mypy. Short-circuits on the first failure.

    Returns a tuple of ``GateResult`` in execution order. On a ruff
    failure the tuple length is 1 (mypy not invoked) — saving the loop
    a slow mypy run on a change that's already going to be discarded.
    On both passing, length is 2.

    Returning a tuple (immutable) keeps callers from accidentally
    mutating the verdict list — important because we persist these
    results into the experiments.jsonl notes field.
    """
    results: list[GateResult] = []
    ruff = run_ruff_gate(changed_files, cwd=cwd, timeout_s=ruff_timeout_s)
    results.append(ruff)
    if ruff.outcome == "fail":
        return tuple(results)

    mypy = run_mypy_gate(changed_files, cwd=cwd, timeout_s=mypy_timeout_s)
    results.append(mypy)
    return tuple(results)


def all_passed(results: tuple[GateResult, ...]) -> bool:
    """Return ``True`` iff every gate in ``results`` passed.

    Helper so callers don't need to know the tuple shape (length 1 on
    short-circuit, length 2 on full run). An empty tuple counts as
    passing — vacuously, no gate failed.
    """
    return all(r.outcome == "pass" for r in results)


def summarize(results: tuple[GateResult, ...]) -> str:
    """Return a short human-readable summary line, or empty if all passed.

    Used by the loop to populate ``diff_summary`` when the iteration is
    discarded for lint regression. Joins individual gate summaries with
    ``" / "`` so multi-failure reads naturally (e.g. ``"ruff: 5
    issue(s) / mypy: 2 error(s)"``).
    """
    failures = [r.summary for r in results if r.outcome == "fail" and r.summary]
    return " / ".join(failures)
