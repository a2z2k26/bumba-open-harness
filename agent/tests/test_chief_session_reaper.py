"""Tests for ``bridge.background_loops.chief_session_reaper_loop`` — Z4-S30 (#1391).

The reaper is the safety net that prevents AWAITING_EVALUATION sessions from
piling up after a chief crash or operator forget. The contract:

  - On each sweep, AWAITING_EVALUATION rows whose ``idle_since_utc`` is
    older than the configured threshold are transitioned
    ``AWAITING_EVALUATION -> TIMED_OUT -> SHUTDOWN`` and persisted.
  - A ``chief_session.timed_out`` event is published per reaped row when an
    event bus is wired.
  - Store / bus failures are best-effort: the loop logs and keeps going.
  - The loop drains-on-shutdown: a pre-set ``shutdown_event`` runs one
    sweep then returns. This is what lets these tests pin the loop to a
    single iteration without relying on a sleep timeout.

The fixture uses ``InMemoryChiefSessionStore`` for fast tests and a
hand-rolled ``MagicMock`` event bus so we can assert exact call shapes
against the registry-defined ``chief_session.timed_out`` event.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from bridge.background_loops import chief_session_reaper_loop
from bridge.chief_session import ChiefSession, ChiefSessionState
from bridge.chief_session_store import InMemoryChiefSessionStore


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _make_idle_session(
    *,
    session_id: str = "cs-idle000000",
    work_order_id: str = "wo-idle",
    department: str = "strategy",
    idle_seconds: float = 3600.0,
) -> ChiefSession:
    """Build a session that has been idle for ``idle_seconds``."""
    return ChiefSession(
        session_id=session_id,
        work_order_id=work_order_id,
        department=department,
        chief_name=f"{department}-chief",
        state=ChiefSessionState.AWAITING_EVALUATION,
        idle_since_utc=_utc_now() - timedelta(seconds=idle_seconds),
    )


@pytest.fixture
def store() -> InMemoryChiefSessionStore:
    return InMemoryChiefSessionStore()


@pytest.fixture
def event_bus() -> MagicMock:
    """Mock event bus with a synchronous ``publish`` (matches EventBus API)."""
    bus = MagicMock()
    bus.publish = MagicMock(return_value=None)
    return bus


# ---------------------------------------------------------------------------
# Happy path — idle session is reaped
# ---------------------------------------------------------------------------


class TestReapIdleSession:
    @pytest.mark.asyncio
    async def test_reaper_transitions_idle_session_to_shutdown(self, store):
        session = _make_idle_session(idle_seconds=3600)
        await store.create(session)

        shutdown = asyncio.Event()
        shutdown.set()  # one sweep then exit

        await chief_session_reaper_loop(
            shutdown,
            chief_session_store=store,
            idle_timeout_seconds=1800,
            event_bus=None,
        )

        final = await store.get(session.session_id)
        assert final.state == ChiefSessionState.SHUTDOWN
        assert final.completed_at_utc is not None

    @pytest.mark.asyncio
    async def test_reaper_does_not_touch_fresh_session(self, store):
        # idle for only 60s — well under the 1800s threshold
        session = _make_idle_session(
            session_id="cs-fresh00000",
            idle_seconds=60,
        )
        await store.create(session)

        shutdown = asyncio.Event()
        shutdown.set()

        await chief_session_reaper_loop(
            shutdown,
            chief_session_store=store,
            idle_timeout_seconds=1800,
            event_bus=None,
        )

        final = await store.get(session.session_id)
        assert final.state == ChiefSessionState.AWAITING_EVALUATION

    @pytest.mark.asyncio
    async def test_reaper_does_not_touch_non_awaiting_state(self, store):
        # An EXECUTING session is older than the threshold but not idle —
        # ``list_idle`` filters by state, so it must not be reaped.
        session = ChiefSession(
            session_id="cs-exec000000",
            work_order_id="wo-exec",
            department="engineering",
            chief_name="engineering-chief",
            state=ChiefSessionState.EXECUTING,
            execution_started_at_utc=_utc_now() - timedelta(seconds=3600),
        )
        await store.create(session)

        shutdown = asyncio.Event()
        shutdown.set()

        await chief_session_reaper_loop(
            shutdown,
            chief_session_store=store,
            idle_timeout_seconds=1800,
            event_bus=None,
        )

        final = await store.get(session.session_id)
        assert final.state == ChiefSessionState.EXECUTING

    @pytest.mark.asyncio
    async def test_reaper_handles_multiple_idle_sessions(self, store):
        # Three idle sessions — all should be reaped in one sweep.
        for i in range(3):
            await store.create(
                _make_idle_session(
                    session_id=f"cs-multi{i:06d}",
                    work_order_id=f"wo-multi-{i}",
                    department="strategy",
                    idle_seconds=3600,
                )
            )

        shutdown = asyncio.Event()
        shutdown.set()

        await chief_session_reaper_loop(
            shutdown,
            chief_session_store=store,
            idle_timeout_seconds=1800,
            event_bus=None,
        )

        for i in range(3):
            final = await store.get(f"cs-multi{i:06d}")
            assert final.state == ChiefSessionState.SHUTDOWN


# ---------------------------------------------------------------------------
# Event bus integration
# ---------------------------------------------------------------------------


class TestEventBusIntegration:
    @pytest.mark.asyncio
    async def test_reaper_publishes_timed_out_event(self, store, event_bus):
        session = _make_idle_session(
            session_id="cs-evt000000",
            work_order_id="wo-evt",
            department="qa",
            idle_seconds=3600,
        )
        await store.create(session)

        shutdown = asyncio.Event()
        shutdown.set()

        await chief_session_reaper_loop(
            shutdown,
            chief_session_store=store,
            idle_timeout_seconds=1800,
            event_bus=event_bus,
        )

        # zone4-warmth.D.01 (#2299) — the reaper now publishes both
        # ``chief_session.history_cleared`` (blob-eviction signal) and
        # ``chief_session.timed_out`` per reaped session. Find the
        # timed_out call explicitly rather than asserting against the
        # last publish (history_cleared also fires).
        event_types = [c.args[0] for c in event_bus.publish.call_args_list]
        assert "chief_session.timed_out" in event_types

        timed_out_call = next(
            c for c in event_bus.publish.call_args_list
            if c.args[0] == "chief_session.timed_out"
        )
        payload = timed_out_call.args[1]
        assert payload["session_id"] == "cs-evt000000"
        assert payload["work_order_id"] == "wo-evt"
        assert payload["department"] == "qa"
        # idle_seconds is computed from idle_since_utc; we asked for ~3600.
        assert 3500 <= payload["idle_seconds"] <= 3700

    @pytest.mark.asyncio
    async def test_reaper_no_event_when_bus_is_none(self, store):
        # Simply exercises the None-bus path; the assertion is that the
        # session is still reaped without raising.
        session = _make_idle_session(
            session_id="cs-nobus000000",
            idle_seconds=3600,
        )
        await store.create(session)

        shutdown = asyncio.Event()
        shutdown.set()

        await chief_session_reaper_loop(
            shutdown,
            chief_session_store=store,
            idle_timeout_seconds=1800,
            event_bus=None,
        )

        final = await store.get("cs-nobus000000")
        assert final.state == ChiefSessionState.SHUTDOWN


# ---------------------------------------------------------------------------
# Resilience — store and bus errors must not kill the loop
# ---------------------------------------------------------------------------


class TestResilience:
    @pytest.mark.asyncio
    async def test_reaper_survives_list_idle_error(self, caplog):
        broken_store = MagicMock()

        async def boom(*args, **kwargs):
            raise RuntimeError("simulated db blip")

        broken_store.list_idle = boom

        shutdown = asyncio.Event()
        shutdown.set()

        with caplog.at_level(logging.WARNING, logger="bridge.background_loops"):
            await chief_session_reaper_loop(
                shutdown,
                chief_session_store=broken_store,
                idle_timeout_seconds=1800,
                event_bus=None,
            )

        # The loop logged the failure and exited cleanly.
        assert any(
            "list_idle failed" in record.message for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_reaper_survives_update_error(self, caplog):
        # Real store for the ``list_idle`` half; mock fails on ``update``.
        store = InMemoryChiefSessionStore()
        await store.create(_make_idle_session(idle_seconds=3600))

        async def boom_update(_):
            raise RuntimeError("update conflict")

        store.update = boom_update  # type: ignore[assignment]

        shutdown = asyncio.Event()
        shutdown.set()

        with caplog.at_level(logging.WARNING, logger="bridge.background_loops"):
            await chief_session_reaper_loop(
                shutdown,
                chief_session_store=store,
                idle_timeout_seconds=1800,
                event_bus=None,
            )

        # We logged a "skipped session" warning and did not raise.
        assert any(
            "skipped session" in record.message for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_reaper_survives_event_bus_error(self, store, caplog):
        broken_bus = MagicMock()

        def boom_publish(*args, **kwargs):
            raise RuntimeError("bus down")

        broken_bus.publish = boom_publish

        await store.create(
            _make_idle_session(
                session_id="cs-busfail0000",
                idle_seconds=3600,
            )
        )

        shutdown = asyncio.Event()
        shutdown.set()

        with caplog.at_level(logging.WARNING, logger="bridge.background_loops"):
            await chief_session_reaper_loop(
                shutdown,
                chief_session_store=store,
                idle_timeout_seconds=1800,
                event_bus=broken_bus,
            )

        # The session was still reaped despite the bus error.
        final = await store.get("cs-busfail0000")
        assert final.state == ChiefSessionState.SHUTDOWN
        # And we logged the publish failure.
        assert any(
            "event publish failed" in record.message for record in caplog.records
        )


# ---------------------------------------------------------------------------
# Shutdown semantics
# ---------------------------------------------------------------------------


class TestShutdownSemantics:
    @pytest.mark.asyncio
    async def test_reaper_exits_when_shutdown_event_set_mid_sleep(self, store):
        # Empty store, very short poll — the loop should sleep on the
        # asyncio.wait_for then exit when we set the shutdown event.
        shutdown = asyncio.Event()

        task = asyncio.create_task(
            chief_session_reaper_loop(
                shutdown,
                chief_session_store=store,
                idle_timeout_seconds=1800,
                event_bus=None,
                poll_interval=10.0,
            )
        )

        # Yield once so the loop gets to its sleep, then signal shutdown.
        await asyncio.sleep(0.05)
        shutdown.set()

        await asyncio.wait_for(task, timeout=2.0)
        assert task.done()
        assert task.exception() is None

    @pytest.mark.asyncio
    async def test_reaper_returns_promptly_when_shutdown_preset(self, store):
        # Pre-set shutdown — the loop should run exactly one sweep and exit.
        await store.create(_make_idle_session(idle_seconds=3600))

        shutdown = asyncio.Event()
        shutdown.set()

        await asyncio.wait_for(
            chief_session_reaper_loop(
                shutdown,
                chief_session_store=store,
                idle_timeout_seconds=1800,
                event_bus=None,
                poll_interval=600.0,  # would block the test if hit
            ),
            timeout=2.0,
        )

        # The pre-set shutdown still produced the single drain sweep.
        final = await store.get("cs-idle000000")
        assert final.state == ChiefSessionState.SHUTDOWN
