"""Tests for agent.bridge.dialogue_delay_monitor.

Sprint 4.13 — Phase 4B (Dialogue-First Communication Architecture).

The delay monitor sits alongside the tool-call gate. Where the gate
catches acknowledgment failures AT turn boundaries, the monitor
catches them DURING work — mid-stream, mid-tool-call, or during long
model thinking when no turn boundary has fired. Together they cover
the full lifecycle of a pending operator message.

These tests exercise the pure-ish tick function with injected
dependencies: a fake clock, a recording metrics sink, and a recording
force-pause alerter. The asyncio start/stop lifecycle is tested
separately with a minimal real event loop.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from bridge.dialogue_delay_monitor import (
    DEFAULT_DELAY_THRESHOLD_SECONDS,
    DEFAULT_FORCE_PAUSE_THRESHOLD_SECONDS,
    DialogueDelayEvent,
    DialogueDelayMonitor,
    EventKind,
)
from bridge.operator_inbox import (
    MessageSeverity,
    OperatorInbox,
    OperatorMessage,
)


# ---------------------------------------------------------------------------
# Test doubles — recording sink + alerter + controllable clock
# ---------------------------------------------------------------------------


@dataclass
class RecordingMetricsSink:
    events: list[DialogueDelayEvent] = field(default_factory=list)

    def log(self, event: DialogueDelayEvent) -> None:
        self.events.append(event)


@dataclass
class RecordingAlerter:
    calls: list[list[OperatorMessage]] = field(default_factory=list)

    async def alert(self, pending: list[OperatorMessage]) -> None:
        # Copy the list so the recorded call is stable even if the
        # caller mutates its own reference afterwards.
        self.calls.append(list(pending))


class FakeClock:
    """A monotonic-style clock under test control.

    The monitor only reads the clock to compute age from
    ``OperatorMessage.received_at``. We return a `datetime` snapshot
    via ``now()``, not a raw monotonic float, because the inbox stores
    aware datetimes and the monitor subtracts them.
    """

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_monitor(
    inbox: OperatorInbox,
    clock: FakeClock,
    *,
    is_agent_active=None,
) -> tuple[DialogueDelayMonitor, RecordingMetricsSink, RecordingAlerter]:
    sink = RecordingMetricsSink()
    alerter = RecordingAlerter()
    monitor = DialogueDelayMonitor(
        inbox=inbox,
        metrics_sink=sink,
        alerter=alerter,
        clock=clock.now,
        delay_threshold_seconds=60,
        force_pause_threshold_seconds=300,
        poll_interval_seconds=10,
        is_agent_active=is_agent_active,
    )
    return monitor, sink, alerter


async def _receive_at(
    inbox: OperatorInbox,
    clock: FakeClock,
    content: str,
    severity: MessageSeverity,
) -> OperatorMessage:
    """Receive a message whose received_at is the current fake-clock time.

    The real ``OperatorInbox.receive`` stamps ``received_at`` from
    ``datetime.now(timezone.utc)``, which ignores our fake clock. So
    we bypass that by constructing the message directly and poking it
    into the inbox's internal list under the lock. This is the ONE
    place the test suite reaches into inbox internals, and it's a
    conscious trade-off — the alternative is either monkey-patching
    ``datetime.now`` (global state, fragile) or adding a clock
    parameter to ``OperatorInbox.receive`` (design pollution for a
    test-only need).
    """
    async with inbox._lock:  # noqa: SLF001 — see docstring rationale
        msg = OperatorMessage(
            id=f"msg_{int(clock.now().timestamp() * 1000)}_{len(inbox._messages) + 1}",
            content=content,
            severity=severity,
            received_at=clock.now(),
        )
        inbox._messages.append(msg)
    return msg


# ---------------------------------------------------------------------------
# EventKind + DialogueDelayEvent dataclass
# ---------------------------------------------------------------------------


def test_event_kind_has_two_values():
    assert {k.name for k in EventKind} == {"DELAY", "FORCE_PAUSE"}


def test_dialogue_delay_event_is_frozen():
    from dataclasses import FrozenInstanceError
    ev = DialogueDelayEvent(
        msg_id="msg_1_1",
        severity=MessageSeverity.QUESTION,
        age_seconds=75.0,
        kind=EventKind.DELAY,
        logged_at=datetime.now(timezone.utc),
    )
    with pytest.raises(FrozenInstanceError):
        ev.age_seconds = 999.0  # type: ignore[misc]


def test_default_thresholds_match_spec():
    """The spec calls for 60s delay threshold and 300s force-pause threshold."""
    assert DEFAULT_DELAY_THRESHOLD_SECONDS == 60
    assert DEFAULT_FORCE_PAUSE_THRESHOLD_SECONDS == 300


# ---------------------------------------------------------------------------
# _tick — empty-inbox fast path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_on_empty_inbox_is_noop():
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    monitor, sink, alerter = _make_monitor(inbox, clock)

    await monitor._tick()

    assert sink.events == []
    assert alerter.calls == []


@pytest.mark.asyncio
async def test_tick_under_delay_threshold_is_noop():
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    monitor, sink, alerter = _make_monitor(inbox, clock)

    await _receive_at(inbox, clock, "recent", MessageSeverity.QUESTION)
    clock.advance(30)  # under 60s threshold

    await monitor._tick()

    assert sink.events == []
    assert alerter.calls == []


# ---------------------------------------------------------------------------
# _tick — delay event at 60s
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_logs_delay_event_when_message_crosses_60s():
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    monitor, sink, alerter = _make_monitor(inbox, clock)

    msg = await _receive_at(inbox, clock, "delayed", MessageSeverity.QUESTION)
    clock.advance(61)

    await monitor._tick()

    assert len(sink.events) == 1
    ev = sink.events[0]
    assert ev.msg_id == msg.id
    assert ev.kind == EventKind.DELAY
    assert ev.severity == MessageSeverity.QUESTION
    assert ev.age_seconds >= 60
    assert alerter.calls == []  # force-pause threshold not yet crossed


@pytest.mark.asyncio
async def test_tick_does_not_log_delay_event_twice_for_same_msg():
    """Regression guard: the monitor must remember which messages it has
    already logged a delay event for. Otherwise every 10s tick after
    the 60s mark would spam the metrics stream with duplicates.
    """
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    monitor, sink, alerter = _make_monitor(inbox, clock)

    await _receive_at(inbox, clock, "delayed", MessageSeverity.QUESTION)
    clock.advance(65)

    await monitor._tick()
    await monitor._tick()
    await monitor._tick()

    assert len(sink.events) == 1


@pytest.mark.asyncio
async def test_tick_does_not_log_delay_for_acked_message():
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    monitor, sink, alerter = _make_monitor(inbox, clock)

    msg = await _receive_at(inbox, clock, "acked", MessageSeverity.INFO)
    await inbox.acknowledge(msg.id)
    clock.advance(120)  # well past the 60s threshold

    await monitor._tick()

    assert sink.events == []


# ---------------------------------------------------------------------------
# _tick — multiple pending messages, mixed ages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_logs_delay_for_each_pending_message_past_threshold():
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    monitor, sink, alerter = _make_monitor(inbox, clock)

    m1 = await _receive_at(inbox, clock, "first", MessageSeverity.INFO)
    clock.advance(30)
    m2 = await _receive_at(inbox, clock, "second", MessageSeverity.QUESTION)
    clock.advance(45)  # m1 is now 75s old, m2 is 45s old

    await monitor._tick()

    assert len(sink.events) == 1
    assert sink.events[0].msg_id == m1.id

    clock.advance(30)  # m1 is now 105s, m2 is 75s

    await monitor._tick()

    # m2 should now also log a delay event
    assert len(sink.events) == 2
    assert {e.msg_id for e in sink.events} == {m1.id, m2.id}


# ---------------------------------------------------------------------------
# _tick — force-pause at 300s
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_triggers_force_pause_past_300s():
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    monitor, sink, alerter = _make_monitor(inbox, clock)

    msg = await _receive_at(inbox, clock, "stale", MessageSeverity.QUESTION)
    clock.advance(301)

    await monitor._tick()

    # Force-pause alerter was called once with the stale message
    assert len(alerter.calls) == 1
    assert [m.id for m in alerter.calls[0]] == [msg.id]


@pytest.mark.asyncio
async def test_tick_does_not_force_pause_twice_for_same_msg():
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    monitor, sink, alerter = _make_monitor(inbox, clock)

    await _receive_at(inbox, clock, "stale", MessageSeverity.QUESTION)
    clock.advance(305)

    await monitor._tick()
    await monitor._tick()
    await monitor._tick()

    assert len(alerter.calls) == 1


@pytest.mark.asyncio
async def test_force_pause_also_logs_a_force_pause_event_to_metrics():
    """The force-pause should emit both an alerter call AND a
    corresponding ``FORCE_PAUSE`` metrics event, so the observability
    record matches the Discord alert.
    """
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    monitor, sink, alerter = _make_monitor(inbox, clock)

    msg = await _receive_at(inbox, clock, "stale", MessageSeverity.QUESTION)
    clock.advance(305)

    await monitor._tick()

    kinds = {e.kind for e in sink.events}
    assert EventKind.DELAY in kinds
    assert EventKind.FORCE_PAUSE in kinds
    force_pause_events = [e for e in sink.events if e.kind == EventKind.FORCE_PAUSE]
    assert len(force_pause_events) == 1
    assert force_pause_events[0].msg_id == msg.id


@pytest.mark.asyncio
async def test_tick_handles_message_that_skips_directly_to_force_pause():
    """If the monitor is spun up after a message has already been
    pending for 400s (e.g. after a session resume), the first tick
    should emit BOTH the delay event and the force-pause event for
    that message, in a single pass.
    """
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    monitor, sink, alerter = _make_monitor(inbox, clock)

    await _receive_at(inbox, clock, "very stale", MessageSeverity.HALT)
    clock.advance(400)

    await monitor._tick()

    assert len(sink.events) == 2
    assert {e.kind for e in sink.events} == {EventKind.DELAY, EventKind.FORCE_PAUSE}
    assert len(alerter.calls) == 1


# ---------------------------------------------------------------------------
# Severity passthrough
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "severity",
    [MessageSeverity.INFO, MessageSeverity.QUESTION, MessageSeverity.HALT],
)
async def test_delay_event_preserves_original_severity(severity):
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    monitor, sink, alerter = _make_monitor(inbox, clock)

    await _receive_at(inbox, clock, "msg", severity)
    clock.advance(65)

    await monitor._tick()

    assert sink.events[0].severity == severity


# ---------------------------------------------------------------------------
# start/stop lifecycle — minimal async exercise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_and_stop_cleanly_cancel_background_task():
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    monitor, sink, alerter = _make_monitor(inbox, clock)

    await monitor.start()
    assert monitor.is_running
    await monitor.stop()
    assert not monitor.is_running


@pytest.mark.asyncio
async def test_stop_is_idempotent():
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    monitor, _, _ = _make_monitor(inbox, clock)

    await monitor.start()
    await monitor.stop()
    assert not monitor.is_running
    # Second stop should not raise and should not hang.
    await monitor.stop()
    # State must remain "not running" after the second stop.
    assert not monitor.is_running


@pytest.mark.asyncio
async def test_start_is_idempotent():
    """Calling start() twice should be safe (the second call returns
    without spawning a duplicate task).
    """
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    monitor, _, _ = _make_monitor(inbox, clock)

    await monitor.start()
    first_task = monitor._task
    assert first_task is not None
    await monitor.start()
    # The second start must not spawn a new task — the existing one is reused.
    assert monitor._task is first_task
    await monitor.stop()
    assert not monitor.is_running


# ---------------------------------------------------------------------------
# Configurability — custom thresholds must override defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_survives_tick_exception_and_keeps_polling():
    """Regression guard (Sprint 4.13 code review): a bug in a single
    tick must not kill the background loop. The `except Exception`
    inside `_run()` swallows and logs; the loop continues.
    """
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()

    call_count = {"n": 0}
    logged_events: list[DialogueDelayEvent] = []

    class FlakySink:
        def log(self, event: DialogueDelayEvent) -> None:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated transient sink failure")
            logged_events.append(event)

    alerter = RecordingAlerter()
    monitor = DialogueDelayMonitor(
        inbox=inbox,
        metrics_sink=FlakySink(),
        alerter=alerter,
        clock=clock.now,
        delay_threshold_seconds=60,
        force_pause_threshold_seconds=300,
        poll_interval_seconds=10,
    )

    await _receive_at(inbox, clock, "delayed", MessageSeverity.QUESTION)
    clock.advance(70)

    # First tick: the sink raises. _tick itself propagates; the
    # background loop's except Exception should catch it. We're
    # testing _run's resilience, not _tick's, so drive it through
    # start/stop with a very short sleep so we observe multiple
    # iterations.
    monitor._poll_interval = 0  # spin tight so the test is fast  # noqa: SLF001
    await monitor.start()
    # Give the loop a few iterations to run, fail, recover, then
    # succeed on a subsequent tick with a new message.
    await asyncio.sleep(0.05)

    # Now add a fresh pending message and advance past the delay
    # threshold so the next successful tick logs it.
    await _receive_at(inbox, clock, "second", MessageSeverity.INFO)
    clock.advance(70)
    await asyncio.sleep(0.05)
    await monitor.stop()

    # The monitor should have kept running past the first failure.
    # At minimum, call_count should exceed 1 (first call raised,
    # later calls succeeded) and at least one successful event
    # should have landed.
    assert call_count["n"] >= 2
    assert len(logged_events) >= 1


@pytest.mark.asyncio
async def test_stop_cancels_cleanly_while_tick_is_awaiting():
    """Regression guard (Sprint 4.13 code review): cancellation during
    an in-flight tick must propagate out so stop() returns promptly
    instead of hanging.
    """
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    sink = RecordingMetricsSink()
    alerter = RecordingAlerter()

    # A slow pending() that would hang for a second if not cancelled.
    original_pending = inbox.pending
    entered = asyncio.Event()

    async def slow_pending() -> list[OperatorMessage]:
        entered.set()
        await asyncio.sleep(10)  # would stall the test if cancellation broke
        return await original_pending()

    inbox.pending = slow_pending  # type: ignore[method-assign]

    monitor = DialogueDelayMonitor(
        inbox=inbox,
        metrics_sink=sink,
        alerter=alerter,
        clock=clock.now,
        delay_threshold_seconds=60,
        force_pause_threshold_seconds=300,
        poll_interval_seconds=10,
    )

    await monitor.start()
    # Wait until the tick has actually entered the slow pending() call
    await asyncio.wait_for(entered.wait(), timeout=1.0)

    # Stop should cancel the tick mid-await and return promptly.
    # A bounded wait_for protects the test from hanging on regression.
    await asyncio.wait_for(monitor.stop(), timeout=1.0)
    assert not monitor.is_running


@pytest.mark.asyncio
async def test_custom_thresholds_are_honored():
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    sink = RecordingMetricsSink()
    alerter = RecordingAlerter()
    monitor = DialogueDelayMonitor(
        inbox=inbox,
        metrics_sink=sink,
        alerter=alerter,
        clock=clock.now,
        delay_threshold_seconds=5,
        force_pause_threshold_seconds=10,
        poll_interval_seconds=1,
    )

    await _receive_at(inbox, clock, "test", MessageSeverity.QUESTION)
    clock.advance(6)
    await monitor._tick()
    assert len(sink.events) == 1
    assert sink.events[0].kind == EventKind.DELAY

    clock.advance(5)  # total age 11s, past the 10s force-pause threshold
    await monitor._tick()
    assert len(alerter.calls) == 1


# ---------------------------------------------------------------------------
# #2207 Part A — force-pause is suppressed when the agent is idle.
# Pre-fix: every threshold crossing posted to Discord, producing the
# BLOCKED-loop the operator hit during late-night conversational sessions.
# Post-fix: alerter is bypassed when is_agent_active() returns False; the
# observability event still fires (cheap + useful for audit).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_suppresses_force_pause_when_agent_idle():
    """#2207 Part A: force-pause does NOT fire when is_agent_active=False."""
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    monitor, sink, alerter = _make_monitor(
        inbox, clock, is_agent_active=lambda: False
    )

    await _receive_at(inbox, clock, "stale", MessageSeverity.QUESTION)
    clock.advance(301)

    await monitor._tick()

    # Alerter not called — agent idle, nothing to interrupt.
    assert alerter.calls == []
    # FORCE_PAUSE observability event still recorded (audit trail).
    kinds = {e.kind for e in sink.events}
    assert EventKind.FORCE_PAUSE in kinds


@pytest.mark.asyncio
async def test_tick_fires_force_pause_when_agent_active():
    """#2207 Part A: force-pause DOES fire when is_agent_active=True."""
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    monitor, sink, alerter = _make_monitor(
        inbox, clock, is_agent_active=lambda: True
    )

    msg = await _receive_at(inbox, clock, "stale", MessageSeverity.QUESTION)
    clock.advance(301)

    await monitor._tick()

    assert len(alerter.calls) == 1
    assert [m.id for m in alerter.calls[0]] == [msg.id]


@pytest.mark.asyncio
async def test_tick_defaults_to_alerting_when_active_check_unwired():
    """#2207 Part A: backward-compat — no is_agent_active arg = always alert."""
    inbox = OperatorInbox(session_id="s1")
    clock = FakeClock()
    # is_agent_active not supplied → pre-#2207 behaviour preserved
    monitor, sink, alerter = _make_monitor(inbox, clock)

    await _receive_at(inbox, clock, "stale", MessageSeverity.QUESTION)
    clock.advance(301)

    await monitor._tick()

    assert len(alerter.calls) == 1
