"""Experiment-loop heartbeat — distinct from ``bridge.heartbeat``.

The experiment loop (``scripts/experiment_loop.py``) runs as its own process
under launchd / nohup. The bridge daemon has no direct visibility into its
state. This module gives the loop a small contract for writing a heartbeat
file on every iteration boundary and gives ``/healthz`` (and the ``/health``
operator command) a defensive way to read it.

Sprint 02.13 / spec ref-audit-02-13 (issue #988).

Design notes:

- File path defaults to ``data/experiment-loop-heartbeat.json`` relative to
  the current working directory. Callers that need a different location can
  pass ``path=...`` explicitly; the bridge passes its absolute runtime path.
- Atomic writes use the standard tmp-then-rename pattern so a partial JSON
  document never leaks to readers.
- ``compute_status`` returns ``unknown`` whenever the file is missing OR the
  recorded PID is no longer running. This keeps ``/healthz`` honest when the
  loop has crashed without updating its own status to ``crashed``.
- The reader is total: malformed / unreadable files always return ``None``
  rather than raise. Heartbeat is observability, not load-bearing logic.

This module does NOT touch ``bridge.heartbeat`` (the dead-man's switch ping
to healthchecks.io). The two are deliberately separate concepts.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

# Default heartbeat path (relative — callers should pass absolute paths in
# production). The runtime layout uses ``/opt/bumba-harness/data/`` whereas
# the source repo uses ``agent/data/``; both resolve via this relative path
# when the caller's CWD is correct.
HEARTBEAT_PATH = Path("data/experiment-loop-heartbeat.json")

# Default stale threshold: 2x the experiment loop's 10-minute tick.
# BridgeConfig exposes this as ``experiment_heartbeat_stale_seconds`` so the
# operator can tune without a code change.
DEFAULT_STALE_THRESHOLD_SECONDS = 1200

ExperimentLoopStatus = Literal["alive", "stale", "unknown"]
LoopWriteStatus = Literal["running", "idle", "crashed"]


@dataclass(frozen=True)
class ExperimentLoopState:
    """One heartbeat record. Written atomically by the loop, read by /healthz.

    ``last_completed_at_iso`` is ``None`` while an iteration is in flight (the
    loop sets ``status='running'`` at iteration start) and populated once the
    iteration finishes. ``fitness_value`` is the trailing iteration's metric
    so /health can surface it without rereading experiments.jsonl.
    """

    last_iter_id: str
    last_started_at_iso: str
    last_completed_at_iso: Optional[str]
    pid: int
    status: LoopWriteStatus
    fitness_value: Optional[float] = None


def is_pid_running(pid: int) -> bool:
    """OS-level pid check via ``os.kill(pid, 0)``.

    Returns True if the PID exists. Defensive against PermissionError (the
    PID exists but is owned by another user — counts as alive) and treats
    any other unexpected error as ``False`` so the caller surfaces
    ``unknown`` rather than ``alive`` on a malformed PID.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # PID exists but is owned by another user.
        return True
    except OSError:
        return False


def _state_from_dict(payload: dict) -> Optional[ExperimentLoopState]:
    """Coerce a deserialized dict into an ExperimentLoopState. Defensive."""
    try:
        return ExperimentLoopState(
            last_iter_id=str(payload["last_iter_id"]),
            last_started_at_iso=str(payload["last_started_at_iso"]),
            last_completed_at_iso=(
                str(payload["last_completed_at_iso"])
                if payload.get("last_completed_at_iso") is not None
                else None
            ),
            pid=int(payload["pid"]),
            status=payload.get("status", "idle"),
            fitness_value=(
                float(payload["fitness_value"])
                if payload.get("fitness_value") is not None
                else None
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None


def write_heartbeat(
    state: ExperimentLoopState,
    *,
    path: Path = HEARTBEAT_PATH,
) -> None:
    """Atomically write the heartbeat file. Idempotent.

    The temp-file is in the same directory as the target so the rename is
    atomic on POSIX. Parent directories are created on demand. This function
    only raises on truly unexpected I/O errors — callers (the experiment
    loop) wrap it in try/except so that a heartbeat-write failure never
    blocks an iteration.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(state)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True))
    tmp.replace(path)


def read_heartbeat(*, path: Path = HEARTBEAT_PATH) -> Optional[ExperimentLoopState]:
    """Read the latest heartbeat. ``None`` on absence or malformed JSON.

    Defensive by design: anything that can go wrong (missing file, bad JSON,
    wrong shape, OS error) collapses to ``None`` so /healthz surfaces
    ``unknown`` rather than 500.
    """
    try:
        if not path.exists():
            return None
        raw = path.read_text()
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return _state_from_dict(payload)


def _parse_iso(value: str) -> Optional[datetime]:
    """Parse an ISO-8601 string into a tz-aware UTC datetime. Returns None on failure."""
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def compute_status(
    *,
    state: Optional[ExperimentLoopState] = None,
    now_iso: Optional[str] = None,
    stale_threshold_seconds: int = DEFAULT_STALE_THRESHOLD_SECONDS,
    path: Path = HEARTBEAT_PATH,
) -> tuple[ExperimentLoopStatus, Optional[float]]:
    """Compute (status, age_seconds) for the heartbeat.

    - ``alive``: heartbeat exists, PID is running, age < threshold
    - ``stale``: heartbeat exists, PID is running, age >= threshold
    - ``unknown``: heartbeat absent, malformed, or recorded PID not running

    ``age_seconds`` is computed against ``last_completed_at_iso`` when set
    (the loop has finished an iteration) and falls back to
    ``last_started_at_iso`` while an iteration is in flight. Returns
    ``(unknown, None)`` whenever a sensible age cannot be derived.
    """
    if state is None:
        state = read_heartbeat(path=path)
    if state is None:
        return ("unknown", None)
    if not is_pid_running(state.pid):
        return ("unknown", None)

    reference_iso = state.last_completed_at_iso or state.last_started_at_iso
    reference_dt = _parse_iso(reference_iso)
    if reference_dt is None:
        return ("unknown", None)

    if now_iso is not None:
        now_dt = _parse_iso(now_iso) or datetime.now(timezone.utc)
    else:
        now_dt = datetime.now(timezone.utc)

    age_seconds = (now_dt - reference_dt).total_seconds()
    if age_seconds < 0:
        age_seconds = 0.0

    if age_seconds < stale_threshold_seconds:
        return ("alive", age_seconds)
    return ("stale", age_seconds)


def healthz_block(
    *,
    path: Path = HEARTBEAT_PATH,
    stale_threshold_seconds: int = DEFAULT_STALE_THRESHOLD_SECONDS,
) -> dict:
    """Render the heartbeat as a /healthz-friendly dict.

    Failure modes degrade to ``status='unknown'`` rather than raise — the
    bridge's health endpoint is best-effort observability.
    """
    try:
        state = read_heartbeat(path=path)
        status, age = compute_status(
            state=state,
            stale_threshold_seconds=stale_threshold_seconds,
            path=path,
        )
        return {
            "experiment_loop_status": status,
            "experiment_loop_last_iter_age_seconds": (
                round(age, 1) if age is not None else None
            ),
            "experiment_loop_pid": state.pid if state is not None else None,
            "experiment_loop_last_iter_id": (
                state.last_iter_id if state is not None else None
            ),
            "experiment_loop_fitness_value": (
                state.fitness_value if state is not None else None
            ),
        }
    except Exception as exc:  # pragma: no cover — last-resort defensive
        logger.warning("experiment_heartbeat block failed: %s", exc)
        return {
            "experiment_loop_status": "unknown",
            "experiment_loop_last_iter_age_seconds": None,
            "experiment_loop_pid": None,
            "experiment_loop_last_iter_id": None,
            "experiment_loop_fitness_value": None,
        }
