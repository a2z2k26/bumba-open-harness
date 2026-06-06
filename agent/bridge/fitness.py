"""Bumba's canonical fitness metric — mean test runtime.

Sprint 02.02 of the 2026-04-25 reference-audit bundle. Operator approved
option 1 (mean test runtime) on 2026-05-01 — see
``docs/plans/2026-04-25-reference-audit/_keystone-decision-pack-2026-05-01.md``.

A single iteration of the experiment loop should be ranked against the
*current* fitness, where lower is better (less time = improvement).
``current_fitness()`` runs ``pytest --durations=0`` over the bridge test
suite and parses every per-test duration line emitted by pytest.

Cost: this is a ~30-second probe (full test suite). Callers MUST NOT
invoke it on every iteration of a tight loop — wrap with the loop-level
cooldown.

Sentinel behaviour: on subprocess crash, parse failure, or zero-sample
output, ``current_fitness`` returns a snapshot with ``value=inf`` and
``sample_count=0``. ``fitness_delta`` consequently reports no
improvement (``before.value - after.value == -inf``) so a broken probe
never silently looks like a win.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


METRIC_NAME = "mean_test_runtime_seconds"
PYTEST_TIMEOUT_SECONDS = 300  # 5 minutes — full bridge suite must fit.

# Per-test duration line emitted by ``pytest --durations=0 -vv``.
# Format: ``<seconds>s <phase> <test_id>`` — e.g. ``0.12s call tests/x.py::Foo``.
# We only count ``call`` rows so we measure user code, not pytest scaffolding.
_DURATION_LINE = re.compile(
    r"^\s*(?P<seconds>\d+(?:\.\d+)?)s\s+call\s+\S+",
    re.MULTILINE,
)


@dataclass(frozen=True)
class FitnessSnapshot:
    """One fitness measurement.

    Frozen dataclass: callers MUST treat snapshots as immutable values.
    Use ``dataclasses.replace`` (or build a new instance) to derive a
    modified version rather than mutating fields.
    """

    metric_name: str
    value: float
    sample_count: int
    captured_at: datetime


def _sentinel(captured_at: datetime | None = None) -> FitnessSnapshot:
    """Return the no-improvement sentinel snapshot."""
    return FitnessSnapshot(
        metric_name=METRIC_NAME,
        value=float("inf"),
        sample_count=0,
        captured_at=captured_at or datetime.now(timezone.utc),
    )


def _parse_durations(stdout: str) -> list[float]:
    """Extract per-test ``call`` durations from ``pytest --durations=0`` output.

    Returns a list of seconds (floats). Empty list signals parse failure
    or a test session that produced no ``call`` rows (e.g. collection error).
    """
    return [float(m.group("seconds")) for m in _DURATION_LINE.finditer(stdout)]


def current_fitness(
    agent_dir: Path | None = None,
    pytest_args: tuple[str, ...] = ("tests/",),
) -> FitnessSnapshot:
    """Probe current fitness by running the test suite once.

    Runs ``pytest --durations=0 -vv -q <pytest_args>`` from ``agent_dir``
    (default: ``<repo>/agent``), parses the per-test ``call`` durations,
    and returns their mean as a ``FitnessSnapshot``. Lower is better.

    On any failure (subprocess timeout, non-zero exit, parse failure, or
    zero samples) returns the no-improvement sentinel.
    """
    if agent_dir is None:
        agent_dir = Path(__file__).resolve().parent.parent
    captured_at = datetime.now(timezone.utc)

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "--durations=0",
        "-vv",
        "-q",
        *pytest_args,
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(agent_dir),
            capture_output=True,
            text=True,
            timeout=PYTEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        log.warning("current_fitness: pytest timed out after %ds", PYTEST_TIMEOUT_SECONDS)
        return _sentinel(captured_at)
    except (OSError, ValueError) as exc:
        log.warning("current_fitness: pytest invocation failed: %s", exc)
        return _sentinel(captured_at)

    # Treat any non-zero exit as untrustworthy. Even one failed test means
    # the duration sample is unrepresentative of "passing" runtime.
    if result.returncode != 0:
        log.warning(
            "current_fitness: pytest exited %d (treating as sentinel)",
            result.returncode,
        )
        return _sentinel(captured_at)

    durations = _parse_durations(result.stdout)
    if not durations:
        log.warning("current_fitness: parsed zero durations from pytest output")
        return _sentinel(captured_at)

    mean = sum(durations) / len(durations)
    return FitnessSnapshot(
        metric_name=METRIC_NAME,
        value=mean,
        sample_count=len(durations),
        captured_at=captured_at,
    )


def fitness_delta(before: FitnessSnapshot, after: FitnessSnapshot) -> float:
    """Return ``before.value - after.value``.

    Positive means improvement (faster after). Negative means regression.
    Sentinels (``value=inf``) propagate naturally: a sentinel ``after``
    yields ``-inf`` (worst possible delta), a sentinel ``before`` yields
    ``+inf`` (uninformative — caller should check ``sample_count > 0``).
    """
    return before.value - after.value
