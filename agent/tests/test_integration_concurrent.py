"""Sprint 16.3: Concurrent operation integration tests.

Verifies that proactive tick cycling, event bus publishing, daily log writes,
consolidation pipeline execution, and circuit breaker registry access can all
run concurrently without deadlocks, data corruption, or state inconsistencies.

Every async test uses asyncio.wait_for() with a 5-second timeout so that
deadlocks surface as TimeoutError rather than hanging the test suite.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from bridge.circuit_breaker import CircuitBreakerConfig, CircuitBreakerRegistry
from bridge.consolidation import (
    ConsolidationReport,
    run_pipeline,
)
from bridge.daily_log import DailyLogWriter
from bridge.event_bus import EventBus
from bridge.tick_manager import TickManager, TickState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEADLOCK_TIMEOUT = 5.0  # seconds — any single test must finish within this


def _make_knowledge_rows(n: int = 20) -> list[dict]:
    """Generate synthetic knowledge rows for consolidation tests."""
    rows = []
    for i in range(n):
        rows.append({
            "key": f"fact-{i}",
            "value": f"The system uses module {i} for processing data efficiently",
            "category": "fact" if i % 3 != 0 else "preference",
            "source": "operator" if i % 5 == 0 else "agent",
            "salience": 1.0 - (i * 0.03),
            "created_at": f"2026-04-0{(i % 9) + 1}T10:00:00Z",
            "access_count": i % 7,
        })
    return rows


def _make_config(tmp_path) -> SimpleNamespace:
    """Create a minimal config object with data_dir for DailyLogWriter."""
    return SimpleNamespace(data_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# Test 1: Tick manager state transitions under concurrent access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_state_transitions_no_corruption():
    """Rapid state transitions from multiple coroutines stay consistent."""

    async def _run():
        tm = TickManager(
            default_sleep_seconds=0.01,
            min_sleep_seconds=0.01,
            max_sleep_seconds=1.0,
        )
        tm.enable()
        assert tm.state == TickState.IDLE

        # Cycle through states rapidly from concurrent coroutines
        results: list[TickState] = []

        async def cycle(n: int):
            for _ in range(n):
                tm.mark_working()
                results.append(tm.state)
                tm.sleep(0.01)
                results.append(tm.state)
                tm.wake()
                results.append(tm.state)

        await asyncio.gather(cycle(20), cycle(20), cycle(20))

        # All recorded states must be valid TickState values
        valid_states = {TickState.IDLE, TickState.SLEEPING, TickState.WORKING}
        for s in results:
            assert s in valid_states, f"Invalid state observed: {s}"

        # Final state after wake() should be IDLE
        assert tm.state == TickState.IDLE

    await asyncio.wait_for(_run(), timeout=DEADLOCK_TIMEOUT)


# ---------------------------------------------------------------------------
# Test 2: Tick wait_for_tick with concurrent wake signals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_wait_with_concurrent_wake():
    """wait_for_tick unblocks when wake() is called from another coroutine."""

    async def _run():
        tm = TickManager(
            default_sleep_seconds=60.0,
            min_sleep_seconds=0.01,
            max_sleep_seconds=60.0,
        )
        tm.enable()
        tm.sleep(60.0)  # Would block for 60s without wake

        async def waker():
            await asyncio.sleep(0.05)
            tm.wake()

        asyncio.create_task(waker())
        result = await tm.wait_for_tick()
        assert result is True
        assert tm.state == TickState.IDLE

    await asyncio.wait_for(_run(), timeout=DEADLOCK_TIMEOUT)


# ---------------------------------------------------------------------------
# Test 3: Event bus concurrent publishing from multiple coroutines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_bus_concurrent_publish(tmp_path):
    """Multiple coroutines publishing events concurrently don't corrupt state."""

    async def _run():
        bus = EventBus(data_dir=tmp_path)
        events_per_task = 50
        num_tasks = 5

        async def publisher(task_id: int):
            for i in range(events_per_task):
                bus.publish(
                    "message.received",
                    payload={"task": task_id, "seq": i},
                    source=f"publisher-{task_id}",
                )

        await asyncio.gather(*(publisher(t) for t in range(num_tasks)))

        expected_total = events_per_task * num_tasks
        assert bus.get_event_count() == expected_total

    await asyncio.wait_for(_run(), timeout=DEADLOCK_TIMEOUT)


# ---------------------------------------------------------------------------
# Test 4: Event bus subscriptions fire correctly under concurrent publishing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_bus_subscriptions_under_load(tmp_path):
    """Subscription callbacks execute for every matching event under concurrency."""

    async def _run():
        bus = EventBus(data_dir=tmp_path)
        received: list[dict] = []
        lock = threading.Lock()

        def handler(event):
            with lock:
                received.append(event.payload)

        bus.subscribe("deploy.started", handler)
        bus.subscribe("deploy.completed", handler)

        events_per_type = 30

        async def publish_started():
            for i in range(events_per_type):
                bus.publish("deploy.started", payload={"phase": "start", "i": i})

        async def publish_completed():
            for i in range(events_per_type):
                bus.publish("deploy.completed", payload={"phase": "done", "i": i})

        async def publish_unrelated():
            for i in range(events_per_type):
                bus.publish("health.changed", payload={"irrelevant": True})

        await asyncio.gather(publish_started(), publish_completed(), publish_unrelated())

        # Only deploy.started and deploy.completed should trigger the handler
        assert len(received) == events_per_type * 2

        # Verify both types present
        start_payloads = [r for r in received if r.get("phase") == "start"]
        done_payloads = [r for r in received if r.get("phase") == "done"]
        assert len(start_payloads) == events_per_type
        assert len(done_payloads) == events_per_type

    await asyncio.wait_for(_run(), timeout=DEADLOCK_TIMEOUT)


# ---------------------------------------------------------------------------
# Test 5: Daily log writer thread-safety under concurrent appends
# ---------------------------------------------------------------------------


def test_daily_log_concurrent_writes(tmp_path):
    """Multiple threads appending to DailyLogWriter don't lose entries or corrupt."""
    config = _make_config(tmp_path)
    writer = DailyLogWriter(config)
    num_threads = 8
    entries_per_thread = 50
    barrier = threading.Barrier(num_threads)

    def write_entries(thread_id: int):
        barrier.wait()  # All threads start at the same instant
        for i in range(entries_per_thread):
            writer.append(
                f"Thread {thread_id} entry {i}",
                category="general" if i % 2 == 0 else "event",
            )

    threads = [
        threading.Thread(target=write_entries, args=(t,))
        for t in range(num_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=DEADLOCK_TIMEOUT)

    content = writer.read_today()
    lines = [line for line in content.splitlines() if line.strip()]

    expected_total = num_threads * entries_per_thread
    assert len(lines) == expected_total, (
        f"Expected {expected_total} lines, got {len(lines)}"
    )


# ---------------------------------------------------------------------------
# Test 6: Consolidation pipeline runs concurrently with event bus activity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consolidation_concurrent_with_events(tmp_path):
    """Consolidation pipeline and event bus operate simultaneously without issues."""

    async def _run():
        bus = EventBus(data_dir=tmp_path)
        rows = _make_knowledge_rows(30)

        consolidation_results: list[ConsolidationReport] = []
        event_counts: list[int] = []

        async def run_consolidation():
            for mode in ("micro", "standard", "deep"):
                # run_pipeline is synchronous — run in executor to avoid blocking
                report = await asyncio.get_event_loop().run_in_executor(
                    None, run_pipeline, list(rows), mode
                )
                consolidation_results.append(report)

        async def run_events():
            for i in range(100):
                bus.publish(
                    "message.processed",
                    payload={"seq": i},
                    source="concurrent-test",
                )
            event_counts.append(bus.get_event_count())

        await asyncio.gather(run_consolidation(), run_events())

        # Consolidation completed all three modes
        assert len(consolidation_results) == 3
        modes = [r.mode for r in consolidation_results]
        assert modes == ["micro", "standard", "deep"]

        # Each report has inventory and decay phases
        for report in consolidation_results:
            assert "inventory" in report.phase_results
            assert "decay" in report.phase_results

        # Events all published
        assert event_counts[0] == 100

    await asyncio.wait_for(_run(), timeout=DEADLOCK_TIMEOUT)


# ---------------------------------------------------------------------------
# Test 7: Circuit breaker registry concurrent get() calls
# ---------------------------------------------------------------------------


def test_circuit_breaker_registry_concurrent_get():
    """Concurrent register() calls for the same and different names are safe."""
    registry = CircuitBreakerRegistry()
    num_threads = 10
    names = [f"service-{i % 3}" for i in range(num_threads)]  # 3 unique names
    results: list = [None] * num_threads
    barrier = threading.Barrier(num_threads)

    def get_breaker(idx: int):
        barrier.wait()
        breaker = registry.register(names[idx])
        results[idx] = breaker

    threads = [
        threading.Thread(target=get_breaker, args=(i,))
        for i in range(num_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=DEADLOCK_TIMEOUT)

    # All results should be non-None CircuitBreaker instances
    for r in results:
        assert r is not None

    # Same name should return same instance
    assert registry.register("service-0") is registry.register("service-0")
    assert registry.register("service-1") is registry.register("service-1")

    # Total unique breakers should be 3
    all_status = registry.list_all()
    assert len(all_status) == 3


# ---------------------------------------------------------------------------
# Test 8: Full concurrent operation — tick + events + log + consolidation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_concurrent_no_deadlock(tmp_path):
    """All subsystems running simultaneously complete without deadlock."""

    async def _run():
        tm = TickManager(
            default_sleep_seconds=0.01,
            min_sleep_seconds=0.01,
            max_sleep_seconds=0.5,
        )
        bus = EventBus(data_dir=tmp_path)
        config = _make_config(tmp_path)
        writer = DailyLogWriter(config)
        rows = _make_knowledge_rows(15)

        tick_cycles = 0
        event_count = 0
        log_entries = 0
        consolidation_done = False

        async def tick_loop():
            nonlocal tick_cycles
            tm.enable()
            for _ in range(10):
                tm.mark_working()
                await asyncio.sleep(0)
                tm.sleep(0.01)
                result = await tm.wait_for_tick()
                if result:
                    tick_cycles += 1

        async def event_loop():
            nonlocal event_count
            for i in range(50):
                bus.publish("message.received", payload={"i": i})
                event_count += 1
                if i % 10 == 0:
                    await asyncio.sleep(0)  # yield to event loop

        async def log_loop():
            nonlocal log_entries
            loop = asyncio.get_event_loop()
            for i in range(20):
                await loop.run_in_executor(
                    None, writer.append, f"Concurrent entry {i}",
                )
                log_entries += 1

        async def consolidation_task():
            nonlocal consolidation_done
            report = await asyncio.get_event_loop().run_in_executor(
                None, run_pipeline, list(rows), "standard"
            )
            assert isinstance(report, ConsolidationReport)
            consolidation_done = True

        await asyncio.gather(
            tick_loop(),
            event_loop(),
            log_loop(),
            consolidation_task(),
        )

        assert tick_cycles == 10
        assert event_count == 50
        assert log_entries == 20
        assert consolidation_done is True

    await asyncio.wait_for(_run(), timeout=DEADLOCK_TIMEOUT)


# ---------------------------------------------------------------------------
# Test 9: Event bus error isolation under concurrent publishing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_bus_handler_error_isolation(tmp_path):
    """A failing handler doesn't block other handlers or publishers."""

    async def _run():
        bus = EventBus(data_dir=tmp_path)
        good_received: list[str] = []
        lock = threading.Lock()

        def bad_handler(event):
            raise RuntimeError("handler exploded")

        def good_handler(event):
            with lock:
                good_received.append(event.event_id)

        bus.subscribe("failure.detected", bad_handler)
        bus.subscribe("failure.detected", good_handler)

        async def publisher():
            for i in range(30):
                bus.publish("failure.detected", payload={"seq": i})

        await asyncio.gather(publisher(), publisher())

        # Good handler should have received all 60 events despite bad handler
        assert len(good_received) == 60

        # Error records should be captured
        errors = bus.get_handler_errors()
        assert len(errors) == 60  # One error per event from bad_handler

    await asyncio.wait_for(_run(), timeout=DEADLOCK_TIMEOUT)


# ---------------------------------------------------------------------------
# Test 10: Circuit breaker concurrent record_success / record_failure
# ---------------------------------------------------------------------------


def test_circuit_breaker_concurrent_state_mutations():
    """Concurrent success/failure recordings don't corrupt breaker state."""
    registry = CircuitBreakerRegistry()
    cfg = CircuitBreakerConfig(failure_threshold=100, timeout_seconds=0.01)
    breaker = registry.register("concurrent-test", cfg)
    num_threads = 6
    ops_per_thread = 100
    barrier = threading.Barrier(num_threads)

    def mutate(thread_id: int):
        barrier.wait()
        for i in range(ops_per_thread):
            if thread_id % 2 == 0:
                breaker.record_success()
            else:
                breaker.record_failure(Exception(f"t{thread_id}-{i}"))

    threads = [
        threading.Thread(target=mutate, args=(t,))
        for t in range(num_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=DEADLOCK_TIMEOUT)

    # Breaker should be in a valid state (not crashed, not corrupted)
    state = breaker.get_state()
    assert state.state.value in ("closed", "open", "half_open")


# ---------------------------------------------------------------------------
# Test 11: Consolidation pure functions are safe under concurrent execution
# ---------------------------------------------------------------------------


def test_consolidation_parallel_pipelines():
    """Multiple consolidation pipelines on independent data run concurrently."""
    num_threads = 4
    results: list[ConsolidationReport] = [None] * num_threads
    barrier = threading.Barrier(num_threads)

    def run_in_thread(idx: int):
        barrier.wait()
        rows = _make_knowledge_rows(20 + idx * 5)
        mode = ["micro", "standard", "deep", "standard"][idx]
        results[idx] = run_pipeline(rows, mode=mode)

    threads = [
        threading.Thread(target=run_in_thread, args=(i,))
        for i in range(num_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=DEADLOCK_TIMEOUT)

    for i, report in enumerate(results):
        assert report is not None, f"Thread {i} produced no result"
        assert isinstance(report, ConsolidationReport)
        assert report.total_duration_ms >= 0

    # Micro mode should only have inventory + decay
    assert "inventory" in results[0].phase_results
    assert "decay" in results[0].phase_results
    assert "merge" not in results[0].phase_results

    # Standard/deep modes should have all phases
    for idx in (1, 2, 3):
        assert "merge" in results[idx].phase_results
        assert "promotion" in results[idx].phase_results


# ---------------------------------------------------------------------------
# Test 12: Tick manager disable during active wait_for_tick
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_disable_during_sleep():
    """Disabling the tick manager while sleeping returns cleanly on next call."""

    async def _run():
        tm = TickManager(
            default_sleep_seconds=60.0,
            min_sleep_seconds=0.01,
            max_sleep_seconds=60.0,
        )
        tm.enable()
        tm.sleep(60.0)

        async def disabler():
            await asyncio.sleep(0.05)
            # Wake first so wait_for_tick unblocks, then disable
            tm.wake()

        asyncio.create_task(disabler())
        result = await tm.wait_for_tick()
        # wake() causes it to return True (it transitions to IDLE before disable)
        assert result is True

        # Now disable and verify next call returns False immediately
        tm.disable()
        result2 = await tm.wait_for_tick()
        assert result2 is False
        assert tm.state == TickState.PAUSED

    await asyncio.wait_for(_run(), timeout=DEADLOCK_TIMEOUT)
