"""Base class for autonomous services (check-in, briefing, etc.).

Services run as scheduled LaunchDaemon jobs or from the bridge idle loop.
They communicate with the bridge via JSON message files in data/service_messages/.

Z2-S4.3 Narration Contract
---------------------------
Every service should narrate what it is doing so the operator always knows
what's running. Two optional helpers are provided:

    self.narrate_start(chat_id, text)
    self.narrate_complete(chat_id, result)

``narrate_start`` posts a message when the service begins its main work.
``narrate_complete`` posts a one-liner summary when the service finishes.

Both are opt-in; calling them is not required for correct service operation.
Services that already post rich output (retro, briefing) typically skip
``narrate_start`` and embed their narration in the body of the main message.

A service SHOULD populate ``ServiceResult.narration`` on every run so the
``/services <name>`` command can surface a human-readable last-run summary,
even if narrate_complete is not called (last_run.json carries the narration).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import ClassVar

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sprint P4.2 — Service skip taxonomy (issue #1589)
# ---------------------------------------------------------------------------
#
# Services can correctly skip a run for several distinct reasons. Before P4.2
# the reason was a free-form string, which meant `/services` and the operator
# could not tell "this is waiting on a credential" from "this had nothing to
# do today". The taxonomy below collapses every skip onto one of six
# operator-actionable classes; the audit plan's acceptance criterion is that
# "service status tells operator exactly what action unlocks each service".
#
# The taxonomy:
#
#   missing_secret:<name>              → operator adds `<name>` to .secrets
#   missing_config:<section.key>       → operator sets `<section.key>` in bridge.toml
#   not_due                            → schedule/window not active; no action
#   dependency_unavailable:<name>      → upstream service/API down; check `<name>`
#   operator_disabled                  → feature flag off; flip flag to enable
#   nothing_to_do                      → ran successfully but no work found; no action
#
# The first four carry a parameter (after the colon) that names the secret,
# config key, or dependency the operator needs to act on. The last two carry
# no parameter — they're terminal classes. `nothing_to_do` is the audit
# plan's gap: services like email "no new mail" or knowledge_review "nothing
# noteworthy" don't fit `not_due` (they ran, the window was open) and they
# don't fit `operator_disabled` (the feature is on). They're informational.


class SkipClass(str, Enum):
    """Top-level category for a service skip.

    Stored in state JSON as ``last_skipped_class`` so ``/services`` can group
    skipped services without re-parsing the reason string. Each value is the
    bare class prefix; parameterised classes append ``:<param>`` in the
    rendered reason string (e.g. ``missing_secret:notion_api_token``).
    """

    MISSING_SECRET = "missing_secret"
    MISSING_CONFIG = "missing_config"
    NOT_DUE = "not_due"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    OPERATOR_DISABLED = "operator_disabled"
    NOTHING_TO_DO = "nothing_to_do"


@dataclass(frozen=True)
class SkipReason:
    """Structured skip reason.

    Construct with a :class:`SkipClass` and an optional parameter or detail.

    For parameterised classes (``missing_secret``, ``missing_config``,
    ``dependency_unavailable``), pass ``detail`` as the parameter name —
    it becomes the suffix after the colon in the rendered string. For
    terminal classes (``not_due``, ``operator_disabled``, ``nothing_to_do``),
    ``detail`` is free-form context for the operator.

    Examples::

        SkipReason(SkipClass.MISSING_SECRET, "notion_api_token")
        # → "missing_secret:notion_api_token"

        SkipReason(SkipClass.NOT_DUE, "outside 09:00-22:00 window")
        # → "not_due (outside 09:00-22:00 window)"

        SkipReason(SkipClass.OPERATOR_DISABLED)
        # → "operator_disabled"
    """

    cls: SkipClass
    detail: str = ""

    _PARAMETERISED: ClassVar[frozenset[SkipClass]] = frozenset(
        {
            SkipClass.MISSING_SECRET,
            SkipClass.MISSING_CONFIG,
            SkipClass.DEPENDENCY_UNAVAILABLE,
        }
    )

    def render(self) -> str:
        """Render as the canonical ``class[:param][ (detail)]`` string."""
        if not self.detail:
            return self.cls.value
        if self.cls in self._PARAMETERISED:
            return f"{self.cls.value}:{self.detail}"
        return f"{self.cls.value} ({self.detail})"


# Required fields in every service state file.
# load_state() merges these defaults with stored state.
#
# Canonical schema — see ``agent/CLAUDE.md`` "Scheduled-service state-file
# schema" section for the operator-facing reference. The probe script at
# ``scripts/audit/s5-1-service-state-probe.sh`` and the health endpoint
# (``bridge/health.py::_check_services``) both consume these fields by name.
REQUIRED_STATE_FIELDS: dict[str, object] = {
    "last_run": None,             # ISO timestamp of last successful run
    "last_status": None,          # "success" | "failure" | "skipped" — terminal class of most recent run (#1806)
    "last_error": None,           # Error message if last run failed
    "last_error_time": None,      # ISO timestamp of last error
    "consecutive_failures": 0,    # Reset to 0 on success OR skip
    "total_runs": 0,              # Lifetime counter (success only)
    "total_failures": 0,          # Lifetime counter
    "total_skipped": 0,           # Lifetime counter (Sprint 3.1 — no-op runs)
    "last_skipped_at": None,      # ISO timestamp of most recent skip
    "last_skipped_reason": None,  # Why the most recent skip happened (rendered string)
    "last_skipped_class": None,   # SkipClass value, e.g. "missing_secret" (P4.2 #1589)
    "last_duration_ms": 0,        # Wall clock of last run
    "total_cost_usd": 0.0,        # Cumulative USD spend across successful runs (Board Phase 1, #2390)
}


class ServiceBase:
    """Base class for autonomous services."""

    def __init__(
        self,
        data_dir: str | Path,
        event_callback: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.messages_dir = self.data_dir / "service_messages"
        self.messages_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir = self.data_dir / "service_state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._event_callback = event_callback

    def deliver_message(
        self,
        chat_id: str,
        text: str,
        *,
        buttons: list[dict[str, str]] | None = None,
        source: str = "service",
    ) -> Path:
        """Write a service message JSON file for bridge pickup.

        Returns the path of the written file.
        """
        msg = {
            "chat_id": chat_id,
            "text": text,
            "source": source,
            "timestamp": time.time(),
        }
        if buttons:
            msg["buttons"] = buttons

        filename = f"{source}_{int(time.time() * 1000)}_{os.getpid()}.json"
        path = self.messages_dir / filename
        path.write_text(json.dumps(msg, indent=2))
        log.info("Service message written: %s", filename)
        return path

    # ------------------------------------------------------------------
    # S4.3 Narration helpers
    # ------------------------------------------------------------------

    def narrate_start(self, chat_id: str, text: str) -> None:
        """Post a one-liner to Discord announcing the service has started.

        Best practice: call this at the top of run() *after* confirming
        should_run() is True so the operator doesn't see narration for
        skipped runs.

        Args:
            chat_id: Discord channel ID.
            text: Short first-person sentence, e.g.
                "Scanning inbox for new mail since last check."
        """
        try:
            self.deliver_message(chat_id, text, source="service_narration")
        except Exception:
            log.debug("narrate_start failed", exc_info=True)

    def narrate_complete(self, chat_id: str, service_name: str, result: object) -> None:
        """Post a one-liner to Discord summarising the completed run.

        Reads ``result.narration`` if set; falls back to the completion line
        from ``format_completion_line(result)``.

        Args:
            chat_id: Discord channel ID.
            service_name: Human-readable service name for the message.
            result: A ``ServiceResult`` instance.
        """
        try:
            from bridge.services.result import format_completion_line

            narration: str | None = getattr(result, "narration", None)
            if not narration:
                narration = format_completion_line(result)

            self.deliver_message(
                chat_id,
                f"[{service_name}] {narration}",
                source="service_narration",
            )
        except Exception:
            log.debug("narrate_complete failed", exc_info=True)

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def load_state(self, filename: str = "service-state.json") -> dict:
        """Load persistent state from a JSON file.

        Checks state_dir first, falls back to data_dir for backwards compat.
        Always returns at least REQUIRED_STATE_FIELDS.
        """
        raw: dict = {}

        path = self.state_dir / filename
        if path.exists():
            try:
                raw = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                raw = {}
        else:
            # Backwards compat: check old location
            old_path = self.data_dir / filename
            if old_path.exists():
                try:
                    raw = json.loads(old_path.read_text())
                except (json.JSONDecodeError, OSError):
                    raw = {}

        # Merge required fields (defaults) with stored state
        merged = {**REQUIRED_STATE_FIELDS, **raw}
        return merged

    def save_state(self, state: dict, filename: str = "service-state.json") -> None:
        """Save persistent state to a JSON file in state_dir.

        Uses atomic write (temp file + os.replace) to prevent corruption
        if the process is killed mid-write.
        """
        # Ensure required fields are present
        for key, default in REQUIRED_STATE_FIELDS.items():
            if key not in state:
                state[key] = default

        path = self.state_dir / filename
        # Atomic write: write to temp, then rename
        fd, tmp_path = tempfile.mkstemp(dir=self.state_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            # Clean up temp file on error
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def record_success(
        self,
        duration_ms: int,
        filename: str = "service-state.json",
        *,
        cost_usd: float = 0.0,
    ) -> None:
        """Record a successful service run.

        Args:
            duration_ms: Wall-clock duration of the run.
            filename: State-file name (``<service>-state.json``).
            cost_usd: USD spend attributed to this run (Board Phase 1, #2390).
                Accumulated into the lifetime ``total_cost_usd`` counter.
                Negative values are clamped to 0.0 — a parser glitch must
                never decrement the cumulative ledger. Skips and failures do
                NOT accrue cost (they don't call this method).
        """
        state = self.load_state(filename)
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        state["last_status"] = "success"
        state["last_error"] = None
        state["consecutive_failures"] = 0
        state["total_runs"] = state.get("total_runs", 0) + 1
        state["last_duration_ms"] = duration_ms
        prior_cost = float(state.get("total_cost_usd", 0.0) or 0.0)
        state["total_cost_usd"] = prior_cost + max(0.0, cost_usd)
        self.save_state(state, filename)

        if self._event_callback:
            service_name = filename.removesuffix("-state.json").removesuffix(".json")
            try:
                self._event_callback("schedule.triggered", {
                    "service": service_name,
                    "status": "success",
                    "duration_ms": duration_ms,
                    "cost_usd": max(0.0, cost_usd),
                })
            except Exception:
                log.debug("Event callback failed in record_success", exc_info=True)

    def record_failure(self, error_msg: str, filename: str = "service-state.json") -> None:
        """Record a failed service run."""
        state = self.load_state(filename)
        state["last_status"] = "failure"
        state["last_error"] = error_msg
        state["last_error_time"] = datetime.now(timezone.utc).isoformat()
        state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        state["total_failures"] = state.get("total_failures", 0) + 1
        self.save_state(state, filename)

        if self._event_callback:
            service_name = filename.removesuffix("-state.json").removesuffix(".json")
            try:
                self._event_callback("failure.detected", {
                    "service": service_name,
                    "error": error_msg,
                    "consecutive_failures": state["consecutive_failures"],
                })
            except Exception:
                log.debug("Event callback failed in record_failure", exc_info=True)

    def record_skipped(
        self,
        reason: SkipReason | str,
        filename: str = "service-state.json",
    ) -> None:
        """Record a no-op service run (Sprint 3.1; taxonomy P4.2 #1589).

        A 'skip' is the correct outcome for some services on most days:
          - knowledge_review when there's nothing noteworthy to surface
          - email when there's no new mail since the last digest
          - briefing when no qualifying sources have data

        Skips are NOT failures and MUST reset consecutive_failures so the
        monitor.sh service-failure tracker doesn't fire false alerts. They
        also are NOT successes — `total_runs` only increments on real work
        being done. The `total_skipped` counter and `last_skipped_*` fields
        provide telemetry without polluting the success/failure semantics.

        ``reason`` accepts either a :class:`SkipReason` (preferred — gives
        the operator an actionable class via ``last_skipped_class``) or a
        plain string (back-compat for services not yet migrated to the
        taxonomy). String reasons are stored verbatim with
        ``last_skipped_class = None``.
        """
        if isinstance(reason, SkipReason):
            rendered = reason.render()
            cls_value: str | None = reason.cls.value
        else:
            rendered = str(reason)
            cls_value = None

        state = self.load_state(filename)
        state["last_status"] = "skipped"
        state["last_skipped_at"] = datetime.now(timezone.utc).isoformat()
        state["last_skipped_reason"] = rendered[:200]
        state["last_skipped_class"] = cls_value
        state["consecutive_failures"] = 0  # critical: reset the failure counter
        state["total_skipped"] = state.get("total_skipped", 0) + 1
        self.save_state(state, filename)

        if self._event_callback:
            service_name = filename.removesuffix("-state.json").removesuffix(".json")
            try:
                self._event_callback("schedule.skipped", {
                    "service": service_name,
                    "reason": rendered,
                    "skip_class": cls_value,
                    "total_skipped": state["total_skipped"],
                })
            except Exception:
                log.debug("Event callback failed in record_skipped", exc_info=True)
