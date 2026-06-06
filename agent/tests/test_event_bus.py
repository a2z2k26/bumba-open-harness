"""Tests for MS5.9 — Event-Driven + Time Hybrid Architecture (EventBus)."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bridge.event_bus import (
    Event,
    EventBus,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bus() -> EventBus:
    """EventBus with no persistence (in-memory only)."""
    return EventBus()


@pytest.fixture
def pbus(tmp_path: Path) -> EventBus:
    """EventBus with persistence to tmp directory."""
    return EventBus(data_dir=tmp_path)


# ---------------------------------------------------------------------------
# TestPublishSubscribe
# ---------------------------------------------------------------------------


class TestPublishSubscribe:
    def test_basic_publish_triggers_callback(self, bus: EventBus):
        received = []
        bus.subscribe("message.received", lambda e: received.append(e))
        bus.publish("message.received", payload={"text": "hello"})
        assert len(received) == 1
        assert received[0].event_type == "message.received"
        assert received[0].payload == {"text": "hello"}

    def test_multiple_subscribers_all_called(self, bus: EventBus):
        calls_a = []
        calls_b = []
        bus.subscribe("deploy.started", lambda e: calls_a.append(e))
        bus.subscribe("deploy.started", lambda e: calls_b.append(e))
        bus.publish("deploy.started")
        assert len(calls_a) == 1
        assert len(calls_b) == 1

    def test_filter_function_filters_events(self, bus: EventBus):
        received = []
        bus.subscribe(
            "health.changed",
            lambda e: received.append(e),
            filter_fn=lambda e: e.payload.get("status") == "critical",
        )
        bus.publish("health.changed", payload={"status": "ok"})
        bus.publish("health.changed", payload={"status": "critical"})
        assert len(received) == 1
        assert received[0].payload["status"] == "critical"

    def test_unsubscribe_stops_callbacks(self, bus: EventBus):
        received = []
        sub_id = bus.subscribe("trust.changed", lambda e: received.append(e))
        bus.publish("trust.changed")
        assert len(received) == 1
        assert bus.unsubscribe(sub_id) is True
        bus.publish("trust.changed")
        assert len(received) == 1  # no new call

    def test_unsubscribe_nonexistent_returns_false(self, bus: EventBus):
        assert bus.unsubscribe("nonexistent_id") is False

    def test_publish_returns_event_with_all_fields(self, bus: EventBus):
        event = bus.publish(
            "deploy.completed",
            payload={"version": "1.2.3"},
            source="deploy_helper",
            correlation_id="chain-001",
        )
        assert isinstance(event, Event)
        assert event.event_type == "deploy.completed"
        assert event.payload == {"version": "1.2.3"}
        assert event.source == "deploy_helper"
        assert event.correlation_id == "chain-001"
        assert len(event.event_id) == 16
        assert event.timestamp  # non-empty ISO string
        assert event.is_replay is False

    def test_subscriber_only_receives_matching_event_type(self, bus: EventBus):
        received = []
        bus.subscribe("deploy.started", lambda e: received.append(e))
        bus.publish("deploy.completed")
        assert len(received) == 0


# ---------------------------------------------------------------------------
# TestEventPersistence
# ---------------------------------------------------------------------------


class TestEventPersistence:
    def test_events_written_to_daily_jsonl(self, pbus: EventBus, tmp_path: Path):
        pbus.publish("message.received", payload={"text": "hi"})
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filepath = tmp_path / "events" / f"{date_str}.jsonl"
        assert filepath.exists()
        lines = filepath.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["event_type"] == "message.received"
        assert data["payload"] == {"text": "hi"}

    def test_replay_returns_persisted_events(self, pbus: EventBus):
        pbus.publish("deploy.started", payload={"v": "1"})
        pbus.publish("deploy.completed", payload={"v": "1"})
        events = pbus.replay()
        assert len(events) == 2
        assert all(e.is_replay is True for e in events)

    def test_replay_filtered_by_event_type(self, pbus: EventBus):
        pbus.publish("deploy.started")
        pbus.publish("deploy.completed")
        pbus.publish("deploy.started")
        events = pbus.replay(event_type="deploy.started")
        assert len(events) == 2
        assert all(e.event_type == "deploy.started" for e in events)

    def test_replay_filtered_by_since_timestamp(self, pbus: EventBus, tmp_path: Path):
        # Write two events manually with known timestamps
        events_dir = tmp_path / "events"
        events_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filepath = events_dir / f"{date_str}.jsonl"
        early = {
            "event_id": "aaa",
            "event_type": "deploy.started",
            "payload": {},
            "source": "",
            "timestamp": "2026-03-14T01:00:00+00:00",
            "correlation_id": None,
        }
        late = {
            "event_id": "bbb",
            "event_type": "deploy.started",
            "payload": {},
            "source": "",
            "timestamp": "2026-03-14T12:00:00+00:00",
            "correlation_id": None,
        }
        filepath.write_text(json.dumps(early) + "\n" + json.dumps(late) + "\n")
        events = pbus.replay(since_timestamp="2026-03-14T10:00:00+00:00")
        assert len(events) == 1
        assert events[0].event_id == "bbb"

    def test_no_persistence_when_data_dir_is_none(self, bus: EventBus):
        # No crash, no file created
        bus.publish("message.received")
        events = bus.replay()
        assert events == []


# ---------------------------------------------------------------------------
# TestCorrelation
# ---------------------------------------------------------------------------


class TestCorrelation:
    def test_start_chain_creates_chain(self, bus: EventBus):
        cid = bus.start_chain()
        chain = bus.get_chain(cid)
        assert chain is not None
        assert chain.status == "in_progress"
        assert chain.started_at != ""

    def test_start_chain_with_explicit_id(self, bus: EventBus):
        cid = bus.start_chain(correlation_id="my-chain")
        assert cid == "my-chain"
        assert bus.get_chain("my-chain") is not None

    def test_events_auto_linked_to_chain(self, bus: EventBus):
        cid = bus.start_chain()
        e1 = bus.publish("deploy.started", correlation_id=cid)
        e2 = bus.publish("deploy.completed", correlation_id=cid)
        chain = bus.get_chain(cid)
        assert e1.event_id in chain.event_ids
        assert e2.event_id in chain.event_ids
        assert len(chain.event_ids) == 2

    def test_complete_chain_changes_status(self, bus: EventBus):
        cid = bus.start_chain()
        assert bus.complete_chain(cid) is True
        assert bus.get_chain(cid).status == "completed"

    def test_fail_chain_changes_status(self, bus: EventBus):
        cid = bus.start_chain()
        assert bus.fail_chain(cid) is True
        assert bus.get_chain(cid).status == "failed"

    def test_complete_nonexistent_chain_returns_false(self, bus: EventBus):
        assert bus.complete_chain("nonexistent") is False

    def test_fail_nonexistent_chain_returns_false(self, bus: EventBus):
        assert bus.fail_chain("nonexistent") is False

    def test_get_active_chains_returns_only_in_progress(self, bus: EventBus):
        cid1 = bus.start_chain()
        cid2 = bus.start_chain()
        cid3 = bus.start_chain()
        bus.complete_chain(cid1)
        bus.fail_chain(cid3)
        active = bus.get_active_chains()
        assert len(active) == 1
        assert active[0].correlation_id == cid2


# ---------------------------------------------------------------------------
# TestFallbackMonitor
# ---------------------------------------------------------------------------


class TestFallbackMonitor:
    def test_check_fallbacks_fires_for_overdue_subscription(self, bus: EventBus):
        received = []
        bus.subscribe(
            "health.changed",
            lambda e: received.append(e),
            expected_interval=1.0,
        )
        # Simulate the subscription having been triggered in the past
        sub = bus.list_subscriptions()[0]
        sub.last_triggered = time.monotonic() - 5.0  # 5s ago, interval is 1s

        triggered = bus.check_fallbacks()
        assert len(triggered) == 1
        assert triggered[0] == sub.id
        assert len(received) == 1
        assert received[0].payload.get("fallback") is True

    def test_check_fallbacks_does_not_fire_for_recent(self, bus: EventBus):
        received = []
        bus.subscribe(
            "health.changed",
            lambda e: received.append(e),
            expected_interval=60.0,
        )
        sub = bus.list_subscriptions()[0]
        sub.last_triggered = time.monotonic()  # just now

        triggered = bus.check_fallbacks()
        assert len(triggered) == 0
        assert len(received) == 0

    def test_fallback_updates_last_triggered(self, bus: EventBus):
        bus.subscribe(
            "schedule.triggered",
            lambda e: None,
            expected_interval=1.0,
        )
        sub = bus.list_subscriptions()[0]
        old_time = time.monotonic() - 10.0
        sub.last_triggered = old_time

        bus.check_fallbacks()
        assert sub.last_triggered > old_time

    def test_check_fallbacks_skips_never_triggered(self, bus: EventBus):
        """Subscriptions with last_triggered=0.0 should not fire fallback."""
        received = []
        bus.subscribe(
            "health.changed",
            lambda e: received.append(e),
            expected_interval=1.0,
        )
        triggered = bus.check_fallbacks()
        assert len(triggered) == 0
        assert len(received) == 0


# ---------------------------------------------------------------------------
# TestHandlerErrors
# ---------------------------------------------------------------------------


class TestHandlerErrors:
    def test_handler_error_does_not_affect_other_handlers(self, bus: EventBus):
        received = []

        def bad_handler(e):
            raise ValueError("kaboom")

        def good_handler(e):
            received.append(e)

        bus.subscribe("failure.detected", bad_handler)
        bus.subscribe("failure.detected", good_handler)
        bus.publish("failure.detected")
        assert len(received) == 1

    def test_handler_error_logged(self, bus: EventBus):
        bus.subscribe("failure.detected", lambda e: 1 / 0)
        bus.publish("failure.detected")
        errors = bus.get_handler_errors()
        assert len(errors) == 1
        assert "division by zero" in errors[0]["error"]
        assert "subscription_id" in errors[0]
        assert "event_id" in errors[0]
        assert "timestamp" in errors[0]

    def test_get_handler_errors_returns_errors(self, bus: EventBus):
        assert bus.get_handler_errors() == []
        bus.subscribe("trust.changed", lambda e: (_ for _ in ()).throw(RuntimeError("oops")))
        bus.publish("trust.changed")
        assert len(bus.get_handler_errors()) == 1


# ---------------------------------------------------------------------------
# TestFormatting
# ---------------------------------------------------------------------------


class TestFormatting:
    def test_format_recent_events(self, bus: EventBus):
        bus.publish("deploy.started", source="test")
        bus.publish("deploy.completed", payload={"version": "1.0"}, source="test")
        output = bus.format_recent_events()
        assert "## Recent Events" in output
        assert "deploy.started" in output
        assert "deploy.completed" in output

    def test_format_recent_events_empty(self, bus: EventBus):
        assert bus.format_recent_events() == "No recent events."

    def test_format_chain(self, bus: EventBus):
        cid = bus.start_chain(correlation_id="test-chain")
        bus.publish("deploy.started", correlation_id=cid)
        output = bus.format_chain(cid)
        assert output is not None
        assert "test-chain" in output
        assert "in_progress" in output
        assert "Events" in output

    def test_format_chain_nonexistent(self, bus: EventBus):
        assert bus.format_chain("nonexistent") is None


# ---------------------------------------------------------------------------
# TestSubscriptionManagement
# ---------------------------------------------------------------------------


class TestSubscriptionManagement:
    def test_get_subscription(self, bus: EventBus):
        sub_id = bus.subscribe("message.received", lambda e: None)
        sub = bus.get_subscription(sub_id)
        assert sub is not None
        assert sub.id == sub_id
        assert sub.event_type == "message.received"

    def test_list_subscriptions(self, bus: EventBus):
        bus.subscribe("deploy.started", lambda e: None)
        bus.subscribe("deploy.completed", lambda e: None)
        subs = bus.list_subscriptions()
        assert len(subs) == 2


# ---------------------------------------------------------------------------
# TestConcurrency
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_concurrent_publish_from_multiple_threads(self, bus: EventBus):
        received = []
        lock = threading.Lock()

        def handler(e):
            with lock:
                received.append(e)

        bus.subscribe("message.received", handler)

        threads = []
        num_threads = 10
        events_per_thread = 50

        def publisher(thread_id):
            for i in range(events_per_thread):
                bus.publish(
                    "message.received",
                    payload={"thread": thread_id, "seq": i},
                    source=f"thread-{thread_id}",
                )

        for t_id in range(num_threads):
            t = threading.Thread(target=publisher, args=(t_id,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(received) == num_threads * events_per_thread
        assert bus.get_event_count() == num_threads * events_per_thread


# ---------------------------------------------------------------------------
# TestEventCount
# ---------------------------------------------------------------------------


class TestEventCount:
    def test_event_count_increments(self, bus: EventBus):
        assert bus.get_event_count() == 0
        bus.publish("message.received")
        bus.publish("message.processed")
        assert bus.get_event_count() == 2
