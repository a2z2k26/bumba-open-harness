"""MAD (Median Absolute Deviation) confidence scoring on fitness deltas.

Sprint 02.04 / spec ref-audit-02-05 (issue #979) of the 2026-04-25
reference-audit bundle. Operator-signed fitness metric: Option 1 — mean
test runtime (``pytest --durations=0``), banked 2026-05-01. See
``docs/plans/2026-04-25-reference-audit/_keystone-decision-pack-2026-05-01.md``.

The experiment loop's keep/discard decision is currently a binary: any
fitness improvement is a "win". That makes it gameable by noise — a
0.001s "improvement" reads as a win even when test-runtime variance is
0.5s. MAD-based confidence fixes this. We compute the median absolute
deviation of recent fitness samples (the *noise floor*) and require any
delta to exceed ``K * MAD`` before treating it as significant.

This sprint **does not** change keep/discard logic; it just exposes the
band to the Discord notifier (Sprint 02.10) and the iteration record on
disk. Sprint 02.05 (next) wires it into the actual decision.

Why MAD over standard deviation: MAD is robust to outliers — one
catastrophic 30s test-runtime spike does not blow up the noise floor
the way ``stdev`` would. With ``K = 2.0`` we get ~95% CI under typical
non-Gaussian noise (the distribution has fat tails because pytest
sessions are interleaved with other system load).

Sentinel behaviour: empty/single-sample/zero-variance inputs return
``mad = 0.0``. ``is_significant`` further requires ``sample_count >= 3``
to fire, so the warm-up window for a fresh ``experiments.jsonl`` is
explicit and safe.
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from bridge.dispatch_metrics import increment_module_counter

log = logging.getLogger(__name__)


# K = 2.0 is the conservative-95% multiplier for non-Gaussian noise.
# K = 1.96 corresponds to 95% under a true Gaussian; we run noisier
# than that, so the operator-signed default sits at 2.0.
K_DEFAULT: float = 2.0
WINDOW_DEFAULT: int = 20
MIN_SAMPLES_FOR_SIGNIFICANCE: int = 3


@dataclass(frozen=True)
class MADResult:
    """Median Absolute Deviation around a median, with sample count.

    Frozen dataclass: callers MUST treat instances as immutable values.
    Use ``dataclasses.replace`` (or build a new instance) to derive a
    modified version rather than mutating fields.

    Fields:
        median: The sample median (robust center).
        mad: The median absolute deviation itself — the robust noise floor.
        sample_count: Number of samples used to compute the result.
        confidence_seconds: ``K * mad`` — the "did the delta move enough"
            threshold. Same units as the input samples (seconds for the
            mean-test-runtime metric).
    """

    median: float
    mad: float
    sample_count: int
    confidence_seconds: float


def compute_mad(values: Iterable[float]) -> float:
    """Median absolute deviation of a sequence.

    Defensive contract:
    * empty input → 0.0 (no spread to measure)
    * single sample → 0.0 (no spread to measure)
    * zero-variance input → 0.0 (correct: every deviation is 0)

    Returns the median of ``|x - median(x)|`` for the input. NumPy and
    SciPy use the same definition under the name ``scipy.stats.median_abs_deviation``.
    """
    samples = [float(v) for v in values]
    if len(samples) < 2:
        return 0.0
    center = statistics.median(samples)
    deviations = [abs(s - center) for s in samples]
    return statistics.median(deviations)


def mad_result(values: Iterable[float], *, k: float = K_DEFAULT) -> MADResult:
    """Build a ``MADResult`` from a sequence of fitness samples.

    ``k`` is the multiplier on MAD that produces the confidence band.
    ``k = 2.0`` corresponds to ~95% CI under typical non-Gaussian noise.
    Callers wanting strict 95% Gaussian semantics should pass ``k = 1.96``.

    Empty input yields ``MADResult(median=0.0, mad=0.0, sample_count=0,
    confidence_seconds=0.0)`` — a vacuously-non-significant band.
    """
    # Determinism Spectrum (Sprint #1115): pure statistical math, Tier 0.
    increment_module_counter("mad_confidence.mad_result", tier=0)
    samples = [float(v) for v in values]
    if not samples:
        return MADResult(median=0.0, mad=0.0, sample_count=0, confidence_seconds=0.0)
    median = statistics.median(samples)
    mad = compute_mad(samples)
    return MADResult(
        median=median,
        mad=mad,
        sample_count=len(samples),
        confidence_seconds=k * mad,
    )


def is_significant(delta: float, result: MADResult) -> bool:
    """Return True iff ``abs(delta) > result.confidence_seconds``.

    Vacuously False when ``result.sample_count < MIN_SAMPLES_FOR_SIGNIFICANCE``
    (default 3) — the warm-up window where we don't have enough samples
    to estimate a noise floor. This is the explicit no-confidence
    sentinel behaviour required by the spec.
    """
    if result.sample_count < MIN_SAMPLES_FOR_SIGNIFICANCE:
        return False
    return abs(delta) > result.confidence_seconds


def load_recent_fitness(jsonl_path: Path | str, *, window: int = WINDOW_DEFAULT) -> list[float]:
    """Read the last ``window`` fitness values from ``experiments.jsonl``.

    Sprint 02.03 persists each iteration as one JSON object per line in
    ``experiments.jsonl`` (see ``scripts.experiment_loop.append_experiments_jsonl``).
    We extract the ``fitness_delta`` field — the per-iteration change in
    the operator-signed mean-test-runtime metric — because MAD on deltas
    is the noise floor we compare new deltas against.

    Defensive contract:
    * file missing → empty list, no exception
    * malformed JSON line → skip + continue
    * record without numeric ``fitness_delta`` → skip + continue
    * fewer than ``window`` valid records → return all of them
    """
    path = Path(jsonl_path)
    if not path.exists():
        return []
    try:
        text = path.read_text()
    except OSError as exc:
        log.warning("load_recent_fitness: cannot read %s: %s", path, exc)
        return []

    values: list[float] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        raw = record.get("fitness_delta")
        if raw is None:
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue

    if window <= 0:
        return []
    return values[-window:]


def confidence_band_seconds(
    metric_name: str = "mean_test_runtime_seconds",
    *,
    jsonl_path: Path | str | None = None,
    window: int = WINDOW_DEFAULT,
    k: float = K_DEFAULT,
) -> float | None:
    """Convenience wrapper used by Sprint 02.10's notifier stub.

    Returns the confidence-band-in-seconds for the current
    ``experiments.jsonl`` window, or ``None`` when there isn't enough
    data to compute a meaningful band (warm-up state).

    ``metric_name`` is accepted for forward-compatibility with future
    multi-metric loops; today only ``mean_test_runtime_seconds`` is
    persisted, and the value is ignored.
    """
    del metric_name  # currently informational only
    if jsonl_path is None:
        # Resolve the default path lazily so importers don't pay the cost.
        # Mirrors the EXPERIMENTS_JSONL_PATH layout defined in
        # scripts/experiment_loop.py without importing the script
        # (importing creates a circular dep through tier_manager).
        repo_agent_dir = Path(__file__).resolve().parent.parent
        jsonl_path = repo_agent_dir / "data" / "experiments.jsonl"

    values = load_recent_fitness(jsonl_path, window=window)
    result = mad_result(values, k=k)
    if result.sample_count < MIN_SAMPLES_FOR_SIGNIFICANCE:
        return None
    return result.confidence_seconds
