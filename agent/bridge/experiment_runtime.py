"""Experiment-loop runtime helpers — first leaf seams extracted from
``scripts/experiment_loop.py`` ahead of the formal demote-split.

Sprint audit-2026-05-16.E.04 (#2072, Section 8.6). The full demote of
``experiment_loop.py`` (3,105 LOC) is scheduled for 2026-05-30. This
module extracts three pure, already-stable leaves so the eventual
demote-split has fewer hot-file collisions to negotiate:

    1. ``_EXPERIMENT_TRAILER_KEY`` + ``_append_experiment_trailers``
       — Sprint E.01 commit-trailer helper (#2069). Idempotent string
       transform; no I/O, no shared state.
    2. ``_parse_validator_subprocess_cost`` — Sprint D.06 stream-JSON
       cost parser (#2067). Pure ``str → CostMeasurement`` decoder
       returning the SW-3 ``measured`` / ``unknown`` shape.
    3. ``_build_halt_policy`` — Sprint C.03 halt-policy factory
       (#2058). Re-shaped to accept ``data_dir: Path`` directly so
       the new module has zero dependency back on ``experiment_loop``.

The dependency direction is strictly one-way: ``experiment_loop``
imports from here; this module never imports from ``experiment_loop``.
``scripts/experiment_loop.py`` keeps a thin re-export block at the
top so existing call sites resolve without change.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING

from bridge.halt import HaltPolicy

if TYPE_CHECKING:
    from bridge.cost_tracker import CostMeasurement


__all__ = [
    "_EXPERIMENT_TRAILER_KEY",
    "_append_experiment_trailers",
    "_parse_validator_subprocess_cost",
    "_build_halt_policy",
]


# ── Sprint audit-2026-05-16.E.01 (#2069) ──────────────────────────────
# Stable trailers on autonomous commits so post-merge inspection and
# rollback triage can filter on
# ``git log --grep='^Bumba-Agent-Experiment: true'`` or render the
# run-id alongside each commit via
# ``git log --format='%h %s [%(trailers:key=Experiment-Run-Id,valueonly)]'``.
_EXPERIMENT_TRAILER_KEY = "Bumba-Agent-Experiment"


def _append_experiment_trailers(message: str, *, run_id: str, mode: str) -> str:
    """Append stable trailers to an experiment-loop commit message.

    Idempotent: a message that already carries
    ``Bumba-Agent-Experiment: true`` is returned unchanged. This lets
    the merge path call us even if the worktree-side pre-commit path
    (``_ensure_worktree_commit``) already added trailers — both call
    sites can stay best-effort without double-stamping.

    The output follows git's trailer convention: a blank line separates
    the message body from the trailers block, and each trailer is a
    single ``Key: Value`` line.
    """
    if f"\n{_EXPERIMENT_TRAILER_KEY}: " in message:
        return message
    trailers = (
        f"{_EXPERIMENT_TRAILER_KEY}: true\n"
        f"Experiment-Run-Id: {run_id}\n"
        f"Experiment-Mode: {mode}\n"
    )
    if message.endswith("\n\n"):
        return message + trailers
    if message.endswith("\n"):
        return message + "\n" + trailers
    return message + "\n\n" + trailers


# ── Sprint audit-2026-05-16.D.06 (#2067) ──────────────────────────────
# Module-level sentinel — distinguishes "key absent" from "key present
# with None value" without colliding with any JSON-deserialised payload.
_MISSING: object = object()


def _parse_validator_subprocess_cost(stdout: str) -> "CostMeasurement":
    """Parse Claude ``-p --output-format stream-json`` stdout for cost.

    Sprint audit-2026-05-16.D.06 (#2067) — replaces the prior
    hardcoded ``cost = 0.0`` fallback in ``_make_validator_runner`` so
    validator-subprocess spend can be distinguished from missing-data.
    Reads the final ``type == "result"`` event (Claude Code emits it
    once per ``-p`` invocation) and returns a ``CostMeasurement``:

      - JSONL line with ``type=="result"`` AND a numeric ``cost_usd``
        field → ``source='measured'`` (preserves measured zero).
      - No result event found, or result event lacks ``cost_usd``,
        or stdout is empty / unparseable → ``source='unknown'``.

    The shape of the cost-knowledge state is the SW-3 invariant from
    D.01: missing data NEVER coerces to ``Decimal('0')`` with
    ``source='measured'``. Callers that store the float in a legacy
    schema MUST branch on the source before recording.
    """
    from bridge.cost_tracker import CostMeasurement as _CM

    if not stdout:
        return _CM(amount_usd=None, source="unknown", backend="claude", raw_usage_id=None)

    last_cost_usd: object = None
    last_session_id: str | None = None
    found_result = False
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            # Non-JSON lines (rare; stderr-style noise on stdout) are
            # ignored. The unknown state below covers the case of
            # no parseable result event surviving the scan.
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "result":
            found_result = True
            # Keep ``last_*`` rather than ``first_*`` — if multiple
            # result events ever appear in one stream (defensive;
            # current Claude Code emits one), the terminal one wins.
            last_cost_usd = event.get("cost_usd", _MISSING)
            sid = event.get("session_id")
            if isinstance(sid, str) and sid:
                last_session_id = sid

    if not found_result or last_cost_usd is _MISSING or last_cost_usd is None:
        return _CM(
            amount_usd=None,
            source="unknown",
            backend="claude",
            raw_usage_id=last_session_id,
        )
    try:
        amount = Decimal(str(last_cost_usd))
    except (InvalidOperation, ValueError, TypeError):
        return _CM(
            amount_usd=None,
            source="unknown",
            backend="claude",
            raw_usage_id=last_session_id,
        )
    return _CM(
        amount_usd=amount,
        source="measured",
        backend="claude",
        raw_usage_id=last_session_id,
    )


# ── Sprint audit-2026-05-16.C.03 (#2058) ──────────────────────────────
# Halt policy factory. The experiment loop runs as a LaunchDaemon child
# with no in-process ``SecurityManager``, so it can't call
# :func:`bridge.config.build_default_halt_policy`. Instead it points the
# policy at the SAME ``halt.flag`` file ``SecurityManager.is_halted()``
# consults so the C.05 + C.03 paths converge on bit-for-bit identical
# halt semantics — one file, one source of truth.
#
# The factory accepts a ``data_dir: Path`` directly (no BridgeConfig
# dependency) so this module stays decoupled from the experiment-loop's
# config-load path. ``experiment_loop.py`` retains a thin wrapper
# (``_build_loop_halt_policy(cfg)``) that resolves cfg.data_dir → Path
# and degrades to a permanently-unblocked policy when cfg is None.


def _build_halt_policy(data_dir: Path) -> HaltPolicy:
    """Build a ``HaltPolicy`` bound to ``<data_dir>/halt.flag``.

    The policy holds two zero-argument callables that re-read the
    halt.flag file on every check (no caching), so a halt that fires
    after policy construction is visible to the next checkpoint without
    rebuilding the policy. Returns a ``HaltPolicy`` with the default
    ``cancel_in_flight=True`` semantics — matches the C.03 contract.

    Args:
        data_dir: Directory holding ``halt.flag``. The same path
            ``SecurityManager`` resolves via ``cfg.data_dir`` — both
            consumers read the same file.
    """
    flag_path = Path(data_dir) / "halt.flag"

    def _is_halted() -> bool:
        return flag_path.exists()

    def _halt_reason() -> str | None:
        if not flag_path.exists():
            return None
        try:
            return flag_path.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    return HaltPolicy(is_halted=_is_halted, halt_reason=_halt_reason)
