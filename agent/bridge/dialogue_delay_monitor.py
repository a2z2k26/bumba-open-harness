"""Dialogue delay monitor — observability and force-pause for pending operator messages.

D7.5 finding F-2: third leg of the dormant Phase-4B triad alongside
operator_inbox + tool_call_gate. D7.9 (#1421) wires all three into
claude_runner so the operator's "messages need to be top priority always"
guarantee becomes observable.

Sprint 4.13 — Phase 4B (Dialogue-First Communication Architecture).

The tool-call gate (Sprint 4.10) catches acknowledgment failures at
turn boundaries: before a new work-tool-call turn starts, it checks
the inbox and blocks if pending messages aren't acknowledged. But the
gate only fires at turn boundaries. If the agent is in the middle of
a long response stream, or mid-tool-call, or thinking for 90 seconds
without producing output, a pending operator message can age silently
with no gate fire and no operator visibility.

This module fills that gap. A background monitor polls the inbox on
a fixed interval (default 10 seconds) during active work and emits
observability events when pending messages cross age thresholds:

- **Delay threshold (default 60s)** — log a single ``DELAY`` event
  to the metrics stream. The operator can see the delay in telemetry;
  no active intervention.
- **Force-pause threshold (default 300s)** — log a ``FORCE_PAUSE``
  event to metrics AND invoke an alerter that posts to Discord (or
  whatever operator-facing channel is wired in). The work loop is
  expected to pause by the caller's response to the alerter.

Both thresholds are idempotent per-message: a given message gets at
most one ``DELAY`` event and at most one ``FORCE_PAUSE`` event
regardless of how many ticks pass after it crosses each threshold.
Acknowledgment removes the message from ``inbox.pending()`` so the
monitor stops seeing it entirely.

Architectural note — why a background poll and not just the gate:

    The gate runs at turn boundaries. The monitor runs on a timer.
    Between turns, the agent can be streaming output, waiting for a
    subprocess, or thinking for an extended period with no gate
    evaluation. The monitor exists specifically to catch the cases
    the gate cannot see. Both layers are needed: the gate is
    enforcement (blocks tool calls), the monitor is observability
    and emergency brake (tells the operator something is wrong and
    pulls the handbrake when things get pathological).

Design — clock injection for testability:

    ``OperatorMessage.age_seconds`` is a ``@property`` that calls
    ``datetime.now(timezone.utc)`` internally. We cannot override it
    without touching the dataclass. The monitor therefore reads
    ``msg.received_at`` directly and computes its own age delta from
    an injected clock callable, bypassing the property. In production
    the clock is ``lambda: datetime.now(timezone.utc)``; in tests it
    is a fake clock the test controls. The ``age_seconds`` property
    is still used by other callers (e.g. the Sprint 4.9 banner) — it
    is not removed.

Integration surface (deferred to the Phase 4B wiring sprint):

    1. At bridge startup, instantiate a ``DialogueDelayMonitor`` with
       the live inbox, a metrics sink (writing to bridge-metrics.jsonl),
       a Discord alerter (the existing Discord bot wrapper), and the
       default thresholds.
    2. Call ``await monitor.start()`` when entering "active work" mode
       (e.g. after receiving a sprint-mode prompt).
    3. Call ``await monitor.stop()`` when work completes or the
       session ends. Stop is idempotent and safe to call multiple
       times.
    4. The monitor's ``_tick()`` method is the pure-ish unit and can
       be invoked directly in tests or diagnostic commands.
"""
from __future__ import annotations

import asyncio
import enum
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from bridge.operator_inbox import (
    MessageSeverity,
    OperatorInbox,
    OperatorMessage,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults (match spec thresholds)
# ---------------------------------------------------------------------------


DEFAULT_DELAY_THRESHOLD_SECONDS: int = 60
DEFAULT_FORCE_PAUSE_THRESHOLD_SECONDS: int = 300
DEFAULT_POLL_INTERVAL_SECONDS: int = 10


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


class EventKind(enum.Enum):
    """Kind of delay observability event.

    - ``DELAY``: a message has been pending longer than the delay
      threshold. Logged once per message. Operator visibility only;
      no active intervention.
    - ``FORCE_PAUSE``: a message has been pending longer than the
      force-pause threshold. Logged once per message AND triggers
      the alerter. The caller (bridge) is expected to pause the
      work loop in response to the alerter call.
    """

    DELAY = "delay"
    FORCE_PAUSE = "force_pause"


@dataclass(frozen=True)
class DialogueDelayEvent:
    """An observability record of a dialogue delay crossing a threshold.

    Attributes:
        msg_id: The ID of the pending operator message that crossed
            the threshold.
        severity: Severity of the message. Carried on the event so
            downstream telemetry can filter on severity without
            needing a join against the inbox.
        age_seconds: The age of the message in seconds at the moment
            the threshold was crossed. This is the monitor's own
            computed age (from ``received_at`` and the injected
            clock), not ``OperatorMessage.age_seconds``.
        kind: Which threshold was crossed (``DELAY`` or
            ``FORCE_PAUSE``).
        logged_at: When the monitor emitted the event. Uses the
            injected clock, so in tests this will be the fake time.
    """

    msg_id: str
    severity: MessageSeverity
    age_seconds: float
    kind: EventKind
    logged_at: datetime


# ---------------------------------------------------------------------------
# Pluggable protocols — metrics sink and force-pause alerter
# ---------------------------------------------------------------------------


class MetricsSink(Protocol):
    """Sink for ``DialogueDelayEvent`` records.

    In production this writes to ``data/bridge-metrics.jsonl``. In
    tests it is a simple list-recorder. The protocol is intentionally
    synchronous so the monitor can log without awaiting I/O on the
    hot path; sinks that need async I/O should buffer and flush on
    their own schedule.
    """

    def log(self, event: DialogueDelayEvent) -> None: ...


class ForcePauseAlerter(Protocol):
    """Alerter for force-pause events.

    In production this posts a Discord message via the existing
    discord_bot wrapper. In tests it is a recording double. The
    protocol is async because Discord posts are network I/O and the
    monitor awaits the alerter before continuing the tick — if the
    alerter is slow, we'd rather the next tick be delayed than drop
    the alert.
    """

    async def alert(self, pending: list[OperatorMessage]) -> None: ...


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------


ClockFn = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


class DialogueDelayMonitor:
    """Background monitor for pending-operator-message age.

    One monitor per bridge session. Constructed with the live inbox
    and injected sink/alerter/clock, then started via ``start()`` at
    the beginning of active work and stopped via ``stop()`` at the
    end. The monitor polls ``inbox.pending()`` on a fixed interval
    and emits events when thresholds are crossed.

    All idempotency state lives in two sets (``_delay_logged`` and
    ``_force_pause_logged``) keyed by ``msg_id``. Because
    ``OperatorMessage.id`` is guaranteed unique per inbox (Sprint
    4.9), these sets can grow unbounded only if the session has
    produced unbounded pending messages — in practice the inbox is
    small and the sets are bounded by the session's total message
    count.
    """

    def __init__(
        self,
        *,
        inbox: OperatorInbox,
        metrics_sink: MetricsSink,
        alerter: ForcePauseAlerter,
        clock: ClockFn = _default_clock,
        delay_threshold_seconds: int = DEFAULT_DELAY_THRESHOLD_SECONDS,
        force_pause_threshold_seconds: int = DEFAULT_FORCE_PAUSE_THRESHOLD_SECONDS,
        poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
        is_agent_active: Callable[[], bool] | None = None,
    ) -> None:
        """
        Args:
            is_agent_active: Optional callable returning True when a Claude
                subprocess is currently running. When provided, the monitor
                will NOT fire the force-pause alert during idle periods —
                there's nothing to interrupt. The DELAY observability event
                still fires regardless. Default (None) preserves the
                pre-#2207 behaviour where every threshold crossing fires
                regardless of agent state.
        """
        if delay_threshold_seconds >= force_pause_threshold_seconds:
            raise ValueError(
                "delay_threshold_seconds must be less than "
                "force_pause_threshold_seconds"
            )
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be > 0")

        self._inbox = inbox
        self._sink = metrics_sink
        self._alerter = alerter
        self._clock = clock
        self._delay_threshold = delay_threshold_seconds
        self._force_pause_threshold = force_pause_threshold_seconds
        self._poll_interval = poll_interval_seconds
        self._is_agent_active = is_agent_active

        self._delay_logged: set[str] = set()
        self._force_pause_logged: set[str] = set()
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the background poll task. Idempotent — calling while
        already running is a no-op.
        """
        if self.is_running:
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel the background task and wait for it to exit.
        Idempotent — safe to call multiple times.
        """
        if self._task is None:
            return
        task = self._task
        self._task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        """Background loop — tick, sleep, repeat until cancelled.

        Cancellation is explicit at both await points. A transient
        exception from ``_tick`` is logged and swallowed so one bad
        tick doesn't kill the monitor — observability is best-effort.
        ``CancelledError`` is re-raised above the generic ``Exception``
        handler so cancellation during an in-flight tick exits the
        loop cleanly and ``stop()`` can await the task to completion.
        """
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("dialogue_delay_monitor: tick failed")
            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                raise

    async def _tick(self) -> None:
        """One pass over the inbox. Emit threshold events as needed.

        This is the pure-ish unit under test. It does not sleep and
        does not touch the background task state — callers can invoke
        it directly in tests without spinning up the full asyncio
        loop machinery.
        """
        pending = await self._inbox.pending()
        if not pending:
            return

        now = self._clock()
        # Snapshot thresholds so tests that modify the monitor between
        # ticks see a consistent view.
        delay_threshold = self._delay_threshold
        force_pause_threshold = self._force_pause_threshold

        force_pause_targets: list[OperatorMessage] = []

        for msg in pending:
            age = (now - msg.received_at).total_seconds()

            if (
                age >= delay_threshold
                and msg.id not in self._delay_logged
            ):
                self._delay_logged.add(msg.id)
                self._sink.log(
                    DialogueDelayEvent(
                        msg_id=msg.id,
                        severity=msg.severity,
                        age_seconds=age,
                        kind=EventKind.DELAY,
                        logged_at=now,
                    )
                )
                logger.warning(
                    "dialogue_delay_monitor: DELAY %s severity=%s age=%.1fs",
                    msg.id,
                    msg.severity.value,
                    age,
                )

            if (
                age >= force_pause_threshold
                and msg.id not in self._force_pause_logged
            ):
                self._force_pause_logged.add(msg.id)
                self._sink.log(
                    DialogueDelayEvent(
                        msg_id=msg.id,
                        severity=msg.severity,
                        age_seconds=age,
                        kind=EventKind.FORCE_PAUSE,
                        logged_at=now,
                    )
                )
                logger.error(
                    "dialogue_delay_monitor: FORCE_PAUSE %s severity=%s age=%.1fs",
                    msg.id,
                    msg.severity.value,
                    age,
                )
                force_pause_targets.append(msg)

        # #2207 Part A: skip the alerter call during idle conversational
        # sessions. The DELAY + FORCE_PAUSE observability events above
        # still fire (they're cheap and useful for audit), but the
        # operator-visible Discord banner only posts when there's an
        # active agent subprocess to interrupt. If `is_agent_active`
        # was not wired, preserve pre-#2207 behaviour (always alert).
        if force_pause_targets:
            if self._is_agent_active is None or self._is_agent_active():
                await self._alerter.alert(force_pause_targets)
            else:
                logger.info(
                    "dialogue_delay_monitor: suppressing force-pause alert "
                    "for %d message(s) — agent is idle (#2207)",
                    len(force_pause_targets),
                )
