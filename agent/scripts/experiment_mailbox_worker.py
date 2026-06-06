"""Worker-side mailbox helpers for the experiment loop (Sprint 15.02, issue #1052).

Spec: ``docs/specs/2026-04-25-reference-audit/spec-15-02-wire-mailbox-into-experimentloop-worktree-boundary-plan-02.md``

Companion to the bridge-side wiring in ``experiment_loop.py``. The
experiment-loop spawns Claude in a git worktree subprocess; before the
spawn it opens a bridge-side ``Mailbox`` and exports the mailbox name +
data-dir as env vars. Inside the subprocess, this module reads those env
vars and lazily opens the corresponding worker-side ``Mailbox`` so the
subprocess can:

- Send ``progress`` messages (mid-iteration breadcrumbs)
- Send ``intermediate_fitness`` measurements before the iteration completes
- Send ``crash`` reports with structured stack traces (vs parsing stderr)
- Read bridge-inbound messages (e.g. ``cancel`` from operator ``/halt``)

All public helpers are **no-op-safe**: when the env vars are absent (the
script is running outside the experiment-loop, e.g. a developer unit test
or a manual ``claude -p`` run), every helper silently returns ``None`` /
``False`` / does nothing. That keeps the worker code path identical
whether or not the loop wiring is enabled — the regression-test
discipline cited in the spec.

Concept-only port informed by the Karpathy NanoClaw v2 dual-DB pattern;
no source code copy.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# The bridge package lives at ``agent/bridge``. When this module is
# imported by ``experiment_loop`` the script's parent already added
# ``agent/`` to ``sys.path``; doing it again here is idempotent and
# guarantees the helper works in standalone subprocess invocations too.
_AGENT_DIR = Path(__file__).resolve().parent.parent
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from bridge.mailbox import Mailbox, MailboxConfig  # noqa: E402

# Env-var contract — keep these names stable across deploys; the bridge
# side of the wiring sets them in ``experiment_loop.run_experiment``
# before spawning the worktree subprocess.
ENV_MAILBOX_NAME = "BUMBA_MAILBOX_NAME"
ENV_MAILBOX_DATA_DIR = "BUMBA_MAILBOX_DATA_DIR"

# Cached worker mailbox + last-seen-cancel state. Module-level cache is
# acceptable because a worker subprocess only ever serves a single
# iteration; the loop spawns a new subprocess per iteration. Tests reset
# state via ``_reset_for_tests``.
_cached_mailbox: Optional[Mailbox] = None
_mailbox_lookup_attempted: bool = False
_cancel_seen: bool = False
_last_cancel_check_seq: int = 0


def _reset_for_tests() -> None:
    """Clear module-level cache. Test-only — production never calls this."""
    global _cached_mailbox, _mailbox_lookup_attempted, _cancel_seen, _last_cancel_check_seq
    if _cached_mailbox is not None:
        try:
            _cached_mailbox.close()
        except Exception:
            pass
    _cached_mailbox = None
    _mailbox_lookup_attempted = False
    _cancel_seen = False
    _last_cancel_check_seq = 0


def get_worker_mailbox() -> Optional[Mailbox]:
    """Open the worker-side mailbox using env vars set by the bridge.

    Returns ``None`` if the required env vars are absent (running outside
    the experiment loop). Cached after the first call so repeated
    progress-reports don't re-open the SQLite connection.
    """
    global _cached_mailbox, _mailbox_lookup_attempted

    if _cached_mailbox is not None:
        return _cached_mailbox
    if _mailbox_lookup_attempted:
        return None

    _mailbox_lookup_attempted = True

    name = os.environ.get(ENV_MAILBOX_NAME)
    if not name:
        return None
    data_dir_str = os.environ.get(ENV_MAILBOX_DATA_DIR, "data")
    config = MailboxConfig(name=name, data_dir=Path(data_dir_str))
    try:
        mbox = Mailbox(config, role="worker")
        mbox.init_db()
    except Exception:
        # Fail-soft: a broken mailbox must NEVER kill the worker.
        return None
    _cached_mailbox = mbox
    return _cached_mailbox


def report_progress(message: str, *, pct: Optional[int] = None) -> None:
    """Send a ``progress`` message to the bridge. No-op if mailbox unavailable.

    Payload shape: ``{"kind": "progress", "message": str, "pct": int|None}``.
    """
    mbox = get_worker_mailbox()
    if mbox is None:
        return
    payload: dict = {"kind": "progress", "message": str(message)}
    if pct is not None:
        payload["pct"] = int(pct)
    try:
        mbox.send(payload)
    except Exception:
        # Fail-soft: a transient SQLite error must NEVER kill the worker.
        return


def report_intermediate_fitness(value: float, *, sample_count: int) -> None:
    """Send an ``intermediate_fitness`` measurement. No-op if mailbox unavailable.

    Payload shape:
    ``{"kind": "intermediate_fitness", "value": float, "sample_count": int}``.
    """
    mbox = get_worker_mailbox()
    if mbox is None:
        return
    payload = {
        "kind": "intermediate_fitness",
        "value": float(value),
        "sample_count": int(sample_count),
    }
    try:
        mbox.send(payload)
    except Exception:
        return


def report_crash(
    error_type: str, message: str, traceback_text: str = ""
) -> None:
    """Send a structured ``crash`` report. No-op if mailbox unavailable.

    Payload shape:
    ``{"kind": "crash", "error_type": str, "message": str, "traceback": str}``.
    """
    mbox = get_worker_mailbox()
    if mbox is None:
        return
    payload = {
        "kind": "crash",
        "error_type": str(error_type),
        "message": str(message),
        "traceback": str(traceback_text),
    }
    try:
        mbox.send(payload)
    except Exception:
        return


def check_cancel() -> bool:
    """Return ``True`` if the bridge has sent a ``cancel`` message.

    Polls the bridge inbound direction since the last successful read.
    Cached: once a cancel has been observed, subsequent calls return
    ``True`` without re-reading SQLite. Returns ``False`` when no
    mailbox is available (running outside the loop).
    """
    global _cancel_seen, _last_cancel_check_seq

    if _cancel_seen:
        return True
    mbox = get_worker_mailbox()
    if mbox is None:
        return False
    try:
        messages = mbox.read_since(after_seq=_last_cancel_check_seq)
    except Exception:
        return False
    for msg in messages:
        if msg.seq > _last_cancel_check_seq:
            _last_cancel_check_seq = msg.seq
        kind = (msg.payload or {}).get("kind")
        if kind == "cancel":
            _cancel_seen = True
            return True
    return False
