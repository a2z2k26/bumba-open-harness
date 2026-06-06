"""Worker-side mailbox helper for the Dark Factory implement workflow.

Sprint 15.03 / issue #1053 — wires Sprint 15.01's :mod:`bridge.mailbox`
primitive into the factory implement workflow boundary (Plan 14, Sprint
14.05). This module is the **worker-side** companion to the bridge-side
wiring inside :mod:`bridge.factory.implement`.

Concept-only port of the NanoClaw v2 dual-DB mailbox pattern (no LICENSE
upstream — `concept-only-no-license` per Plan 15). The factory implement
worker is the Claude subprocess spawned inside an isolated git worktree;
this module gives that subprocess a small, dependency-free API for
streaming structured events back to the bridge while the run is in
flight (progress, decision requests, partial cost telemetry) and for
checking whether the bridge has asked it to cancel.

Design contract
---------------
- The bridge opens the mailbox before spawning the worker and passes
  ``BUMBA_MAILBOX_NAME`` + ``BUMBA_MAILBOX_DATA_DIR`` via env vars. To
  keep the experiment-loop and factory mailboxes from cross-talking, the
  worker helper here only matches names that start with
  ``factory_implement_`` (the experiment loop uses its own prefix).
- All functions are **no-ops** when the env vars are absent. The
  implement workflow predates the mailbox; the worker must continue to
  run when the operator has the ``factory_mailbox_enabled`` flag OFF.
- Cancel and decision-response messages are read from the bridge-side
  DB (``bridge_to_worker`` direction). The helper tracks an internal
  cursor so concurrent ``check_cancel`` / ``request_decision`` calls
  don't double-consume.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

from bridge.mailbox import Mailbox, MailboxConfig

logger = logging.getLogger(__name__)


# ── Env-var contract ────────────────────────────────────────────────────

ENV_MAILBOX_NAME = "BUMBA_MAILBOX_NAME"
ENV_MAILBOX_DATA_DIR = "BUMBA_MAILBOX_DATA_DIR"
FACTORY_MAILBOX_NAME_PREFIX = "factory_implement_"
DEFAULT_DATA_DIR = "data/factory-mailboxes"

# ── Payload-type discriminators ─────────────────────────────────────────
# Worker → bridge:
PAYLOAD_TYPE_PROGRESS = "progress"
PAYLOAD_TYPE_DECISION_REQUEST = "decision_request"
PAYLOAD_TYPE_PARTIAL_COST = "partial_cost"
# Bridge → worker:
PAYLOAD_TYPE_CANCEL = "cancel"
PAYLOAD_TYPE_CLARIFY_RESPONSE = "clarify_response"

# Polling interval when blocking on a decision response.
_DECISION_POLL_INTERVAL_SEC = 1.0


# ── Public helpers ──────────────────────────────────────────────────────


def get_implement_worker_mailbox() -> Optional[Mailbox]:
    """Open the worker-side mailbox using env vars set by the bridge.

    Returns ``None`` if the env vars are absent or the mailbox name does
    not match the ``factory_implement_`` prefix — this lets the helper
    coexist with sibling worker mailboxes (e.g. experiment loop) without
    accidentally cross-talking.

    Never raises. The bridge guarantees the env vars when
    ``factory_mailbox_enabled`` is ON; OFF means no env vars and we
    return None silently.
    """
    name = os.environ.get(ENV_MAILBOX_NAME)
    if not name or not name.startswith(FACTORY_MAILBOX_NAME_PREFIX):
        return None
    data_dir = Path(os.environ.get(ENV_MAILBOX_DATA_DIR, DEFAULT_DATA_DIR))
    config = MailboxConfig(name=name, data_dir=data_dir)
    try:
        mailbox = Mailbox(config, role="worker")
        mailbox.init_db()
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "implement_mailbox_worker: failed to open mailbox %r: %s",
            name, exc,
        )
        return None
    return mailbox


def report_progress(
    phase: str,
    *,
    message: str = "",
    pct: Optional[int] = None,
    mailbox: Optional[Mailbox] = None,
) -> None:
    """Send a progress message. No-op when the mailbox is unavailable.

    ``phase`` is the implement-pipeline phase identifier (see
    :mod:`bridge.factory.implement` ``PHASE_*`` constants). ``pct`` is an
    optional 0-100 progress hint; the bridge surfaces it in operator
    status output.
    """
    mb = mailbox if mailbox is not None else get_implement_worker_mailbox()
    if mb is None:
        return
    payload = {
        "type": PAYLOAD_TYPE_PROGRESS,
        "phase": phase,
        "message": message,
        "pct": pct,
    }
    try:
        mb.send(payload)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "implement_mailbox_worker: report_progress send failed: %s", exc
        )


def request_decision(
    question: str,
    *,
    choices: Optional[list[str]] = None,
    timeout_seconds: int = 3600,
    mailbox: Optional[Mailbox] = None,
    sleep_fn=time.sleep,
) -> Optional[str]:
    """Block until the bridge sends a clarify_response, or timeout/cancel.

    Returns the operator's chosen string, or ``None`` if:
      - the mailbox is unavailable (factory_mailbox_enabled=False),
      - the timeout elapses,
      - a cancel arrives before the response,
      - the bridge sends a malformed clarify_response payload.

    ``sleep_fn`` is an injection seam for tests so the polling loop does
    not actually block the test runner.
    """
    mb = mailbox if mailbox is not None else get_implement_worker_mailbox()
    if mb is None:
        return None

    # Capture the cursor BEFORE we send so we only pick up responses to
    # our request. Using ``latest_seq`` instead of 0 also makes the
    # helper tolerant to historical messages the orchestrator may have
    # left in the bridge DB during a previous run.
    cursor = mb.latest_seq()

    payload = {
        "type": PAYLOAD_TYPE_DECISION_REQUEST,
        "question": question,
        "choices": list(choices) if choices is not None else None,
    }
    try:
        mb.send(payload)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "implement_mailbox_worker: request_decision send failed: %s", exc
        )
        return None

    deadline = time.monotonic() + max(0, int(timeout_seconds))
    while time.monotonic() < deadline:
        try:
            messages = mb.read_since(after_seq=cursor, limit=50)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                "implement_mailbox_worker: request_decision read failed: %s",
                exc,
            )
            return None

        for msg in messages:
            cursor = msg.seq
            payload_type = msg.payload.get("type") if isinstance(msg.payload, dict) else None
            if payload_type == PAYLOAD_TYPE_CANCEL:
                return None
            if payload_type == PAYLOAD_TYPE_CLARIFY_RESPONSE:
                choice = msg.payload.get("choice")
                if isinstance(choice, str):
                    return choice
                # Malformed response — treat as no answer.
                return None

        sleep_fn(_DECISION_POLL_INTERVAL_SEC)

    return None


def check_cancel(mailbox: Optional[Mailbox] = None) -> bool:
    """Return ``True`` iff the bridge has sent a cancel message.

    Non-blocking. The helper reads ``bridge_to_worker`` messages from
    seq 0 every call — cancel is sticky, so once observed it must keep
    returning True until the worker exits. Cheap because the bridge DB
    is normally near-empty for a given run.
    """
    mb = mailbox if mailbox is not None else get_implement_worker_mailbox()
    if mb is None:
        return False
    try:
        messages = mb.read_since(after_seq=0, limit=1000)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "implement_mailbox_worker: check_cancel read failed: %s", exc
        )
        return False
    for msg in messages:
        if isinstance(msg.payload, dict) and msg.payload.get("type") == PAYLOAD_TYPE_CANCEL:
            return True
    return False


def report_partial_cost(
    cost_usd: float,
    *,
    model: str,
    mailbox: Optional[Mailbox] = None,
) -> None:
    """Stream partial-cost telemetry to the bridge. No-op when unavailable.

    The bridge orchestrator uses these to enforce mid-flight budget caps;
    sending more often than once per phase is fine — costs are additive.
    """
    mb = mailbox if mailbox is not None else get_implement_worker_mailbox()
    if mb is None:
        return
    payload = {
        "type": PAYLOAD_TYPE_PARTIAL_COST,
        "cost_usd": float(cost_usd),
        "model": str(model),
    }
    try:
        mb.send(payload)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "implement_mailbox_worker: report_partial_cost send failed: %s",
            exc,
        )


__all__ = [
    "ENV_MAILBOX_DATA_DIR",
    "ENV_MAILBOX_NAME",
    "FACTORY_MAILBOX_NAME_PREFIX",
    "PAYLOAD_TYPE_CANCEL",
    "PAYLOAD_TYPE_CLARIFY_RESPONSE",
    "PAYLOAD_TYPE_DECISION_REQUEST",
    "PAYLOAD_TYPE_PARTIAL_COST",
    "PAYLOAD_TYPE_PROGRESS",
    "check_cancel",
    "get_implement_worker_mailbox",
    "report_partial_cost",
    "report_progress",
    "request_decision",
]
