"""Sprint 16.2 — Failure cascade integration tests.

Exercises the full failure path:
  API timeout -> retry -> circuit breaker trips -> escalation fires -> event bus publishes

Tests cover:
  - Circuit breaker state machine (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
  - Escalation trigger levels (3 failures = NUDGE, 5 = URGENT)
  - De-escalation when failures clear
  - Event bus correlation chains through a failure scenario
  - Quiet-hours filtering of escalation alerts
  - Full end-to-end cascade wiring all three modules together
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from bridge.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerRegistry,
    State as BreakerState,
)
from bridge.escalation import ActiveAlert, EscalationEngine, EscalationLevel
from bridge.event_bus import EventBus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def breaker():
    """A circuit breaker with low threshold for fast testing."""
    return CircuitBreaker(CircuitBreakerConfig(failure_threshold=5, timeout_seconds=10.0, window_seconds=60.0))


@pytest.fixture
def registry():
    return CircuitBreakerRegistry()


@pytest.fixture
def escalation(tmp_path):
    return EscalationEngine(state_dir=tmp_path, operator_mention="<@operator>")


@pytest.fixture
def bus(tmp_path):
    return EventBus(data_dir=tmp_path)


# ---------------------------------------------------------------------------
# 1. Circuit breaker state transitions: CLOSED -> OPEN -> HALF_OPEN -> CLOSED
# ---------------------------------------------------------------------------

class TestCircuitBreakerStateMachine:
    """Verify the full circuit breaker lifecycle."""

    def test_closed_to_open_after_threshold_failures(self, breaker):
        """Five consecutive failures trip the breaker from CLOSED to OPEN."""
        assert breaker.get_state().state == BreakerState.CLOSED

        for i in range(4):
            breaker.record_failure(Exception(f"timeout #{i + 1}"))
            assert breaker.get_state().state == BreakerState.CLOSED, (
                f"Should remain CLOSED after {i + 1} failures (threshold=5)"
            )

        # Fifth failure trips the breaker
        breaker.record_failure(Exception("timeout #5"))
        state = breaker.get_state()
        assert state.state == BreakerState.OPEN
        assert state.failure_count == 5

    def test_open_to_half_open_after_recovery_timeout(self, breaker):
        """After timeout_seconds elapses, OPEN transitions to HALF_OPEN."""
        for _ in range(5):
            breaker.record_failure(Exception("timeout"))
        assert breaker.get_state().state == BreakerState.OPEN

        with patch("bridge.circuit_breaker.time") as mock_time:
            mock_time.monotonic.return_value = breaker._opened_at + 11.0
            assert breaker.get_state().state == BreakerState.HALF_OPEN

    def test_half_open_to_closed_on_success(self, breaker):
        """A successful request in HALF_OPEN returns to CLOSED."""
        for _ in range(5):
            breaker.record_failure(Exception("timeout"))

        with patch("bridge.circuit_breaker.time") as mock_time:
            mock_time.monotonic.return_value = breaker._opened_at + 11.0
            _ = breaker.get_state()  # trigger transition

        assert breaker._state == BreakerState.HALF_OPEN

        # success_threshold=2, so two successes needed
        breaker.record_success()
        breaker.record_success()
        assert breaker._state == BreakerState.CLOSED

    def test_half_open_to_open_on_failure(self, breaker):
        """A failure in HALF_OPEN re-opens the breaker immediately."""
        for _ in range(5):
            breaker.record_failure(Exception("timeout"))

        with patch("bridge.circuit_breaker.time") as mock_time:
            mock_time.monotonic.return_value = breaker._opened_at + 11.0
            _ = breaker.get_state()

        assert breaker._state == BreakerState.HALF_OPEN
        breaker.record_failure(Exception("still failing"))
        assert breaker._state == BreakerState.OPEN


# ---------------------------------------------------------------------------
# 2. Circuit breaker registry
# ---------------------------------------------------------------------------

class TestCircuitBreakerRegistry:

    def test_registry_creates_and_reuses_breakers(self, registry):
        """Registry creates breakers on first access and reuses them."""
        b1 = registry.register("service_a", CircuitBreakerConfig(failure_threshold=3))
        b2 = registry.get("service_a")
        assert b1 is b2

        b3 = registry.register("service_b", CircuitBreakerConfig(failure_threshold=10))
        assert b3 is not b1

        all_states = registry.list_all()
        assert len(all_states) == 2
        assert set(all_states.keys()) == {"service_a", "service_b"}


# ---------------------------------------------------------------------------
# 3. Escalation trigger levels
# ---------------------------------------------------------------------------

class TestEscalationTriggerLevels:

    def test_three_failures_triggers_nudge(self, escalation):
        """3 consecutive failures produce a NUDGE-level alert."""
        states = {
            "api_gateway": {
                "consecutive_failures": 3,
                "last_error": "Connection timeout",
            }
        }
        alerts = escalation.evaluate_triggers(states)
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.level == EscalationLevel.NUDGE
        assert alert.source == "api_gateway"
        assert "3 consecutive failures" in alert.message

    def test_five_failures_triggers_urgent(self, escalation):
        """5 consecutive failures produce an URGENT-level alert."""
        states = {
            "api_gateway": {
                "consecutive_failures": 5,
                "last_error": "Connection timeout",
            }
        }
        alerts = escalation.evaluate_triggers(states)
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.level == EscalationLevel.URGENT
        assert alert.source == "api_gateway"
        assert "5 consecutive failures" in alert.message

    def test_duplicate_alert_suppressed_by_cooldown(self, escalation):
        """Same source alert is suppressed within cooldown window."""
        states = {
            "api_gateway": {
                "consecutive_failures": 5,
                "last_error": "timeout",
            }
        }
        alerts_1 = escalation.evaluate_triggers(states)
        assert len(alerts_1) == 1

        # Second evaluation within cooldown -- should not produce new alert
        alerts_2 = escalation.evaluate_triggers(states)
        assert len(alerts_2) == 0


# ---------------------------------------------------------------------------
# 4. De-escalation
# ---------------------------------------------------------------------------

class TestDeEscalation:

    def test_alert_clears_when_failures_resolve(self, escalation):
        """When consecutive_failures returns to 0, the alert is de-escalated."""
        # First, trigger an alert
        failing_states = {
            "api_gateway": {"consecutive_failures": 5, "last_error": "timeout"},
        }
        alerts = escalation.evaluate_triggers(failing_states)
        assert len(alerts) == 1

        # Now the service recovers
        recovered_states = {
            "api_gateway": {"consecutive_failures": 0, "last_error": None},
        }
        cleared = escalation.check_de_escalation(recovered_states)
        assert "api_gateway" in cleared

        # After de-escalation + cooldown expiry, a new failure would trigger again.
        # But within cooldown it won't (tested separately).


# ---------------------------------------------------------------------------
# 5. Quiet hours filtering
# ---------------------------------------------------------------------------

class TestQuietHoursFiltering:

    def _make_alert(self, level: EscalationLevel, source: str = "test") -> ActiveAlert:
        now_iso = datetime.now(timezone.utc).isoformat()
        return ActiveAlert(
            source=source,
            level=level,
            message=f"{source} alert",
            triggered_at=now_iso,
            last_notified_at=now_iso,
        )

    def test_quiet_hours_defers_nudge_delivers_urgent(self, escalation):
        """During quiet hours, NUDGE is deferred, URGENT delivers immediately."""
        alerts = [
            self._make_alert(EscalationLevel.URGENT, source="critical_svc"),
            self._make_alert(EscalationLevel.NUDGE, source="warn_svc"),
            self._make_alert(EscalationLevel.CASUAL, source="info_svc"),
        ]

        # Simulate quiet hours (03:00 ET)
        with patch("bridge.escalation.datetime") as mock_dt:
            mock_now = datetime(2026, 4, 3, 3, 0, 0)
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            deliver, defer = escalation.apply_quiet_hours(alerts)

        # URGENT and CASUAL delivered, NUDGE deferred
        assert len(deliver) == 2
        assert any(a.source == "critical_svc" for a in deliver)
        assert any(a.source == "info_svc" for a in deliver)

        assert len(defer) == 1
        assert defer[0].source == "warn_svc"
        assert defer[0].deferred is True

    def test_non_quiet_hours_delivers_all(self, escalation):
        """Outside quiet hours, all alerts deliver immediately."""
        alerts = [
            self._make_alert(EscalationLevel.URGENT, source="critical_svc"),
            self._make_alert(EscalationLevel.NUDGE, source="warn_svc"),
        ]

        # Simulate 14:00 ET (not quiet hours)
        with patch("bridge.escalation.datetime") as mock_dt:
            mock_now = datetime(2026, 4, 3, 14, 0, 0)
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            deliver, defer = escalation.apply_quiet_hours(alerts)

        assert len(deliver) == 2
        assert len(defer) == 0


# ---------------------------------------------------------------------------
# 6. Event bus correlation chains through failure scenario
# ---------------------------------------------------------------------------

class TestEventBusCorrelationChains:

    def test_chain_tracks_events_through_failure_lifecycle(self, bus):
        """A correlation chain collects events from detection through escalation."""
        cid = bus.start_chain()
        chain = bus.get_chain(cid)
        assert chain is not None
        assert chain.status == "in_progress"
        assert len(chain.event_ids) == 0

        # Publish failure detection
        e1 = bus.publish("failure.detected", payload={"service": "api_gateway"}, source="monitor", correlation_id=cid)
        # Publish escalation
        e2 = bus.publish("failure.escalated", payload={"level": "URGENT"}, source="escalation", correlation_id=cid)

        chain = bus.get_chain(cid)
        assert len(chain.event_ids) == 2
        assert e1.event_id in chain.event_ids
        assert e2.event_id in chain.event_ids

        # Mark chain failed
        assert bus.fail_chain(cid) is True
        chain = bus.get_chain(cid)
        assert chain.status == "failed"

    def test_chain_completes_on_recovery(self, bus):
        """A chain transitions to completed when the service recovers."""
        cid = bus.start_chain()

        bus.publish("failure.detected", payload={"service": "api_gateway"}, correlation_id=cid)
        bus.publish("failure.recovered", payload={"service": "api_gateway"}, correlation_id=cid)

        assert bus.complete_chain(cid) is True
        chain = bus.get_chain(cid)
        assert chain.status == "completed"
        assert len(chain.event_ids) == 2

    def test_subscriber_receives_correlated_events(self, bus):
        """Subscribers fire for correlated events and can inspect correlation_id."""
        received = []
        bus.subscribe("failure.detected", callback=lambda e: received.append(e))

        cid = bus.start_chain()
        bus.publish("failure.detected", payload={"count": 5}, correlation_id=cid)

        assert len(received) == 1
        assert received[0].correlation_id == cid
        assert received[0].payload["count"] == 5


# ---------------------------------------------------------------------------
# 7. Full end-to-end failure cascade
# ---------------------------------------------------------------------------

class TestFullFailureCascade:
    """Wire circuit breaker, escalation, and event bus into a single scenario.

    Scenario:
      1. Simulate 5 API timeouts with retries
      2. Circuit breaker trips (CLOSED -> OPEN)
      3. Escalation engine fires URGENT alert
      4. Event bus publishes failure.detected + failure.escalated
      5. Service recovers -> circuit breaker resets -> de-escalation -> chain completes
    """

    def test_end_to_end_failure_and_recovery(self, tmp_path):
        """Full cascade: failures -> breaker trip -> escalation -> events -> recovery."""
        breaker = CircuitBreaker(name="api_gateway", failure_threshold=5, recovery_timeout=2.0)
        escalation = EscalationEngine(state_dir=tmp_path)
        bus = EventBus(data_dir=tmp_path)

        # Track published events
        all_events = []
        bus.subscribe("failure.detected", callback=lambda e: all_events.append(e))
        bus.subscribe("failure.escalated", callback=lambda e: all_events.append(e))
        bus.subscribe("failure.recovered", callback=lambda e: all_events.append(e))

        cid = bus.start_chain()

        # --- Phase 1: Accumulate failures ---
        for i in range(5):
            breaker.record_failure(reason=f"timeout #{i + 1}")
            bus.publish(
                "failure.detected",
                payload={"service": "api_gateway", "attempt": i + 1, "reason": f"timeout #{i + 1}"},
                source="retry_handler",
                correlation_id=cid,
            )

        # Circuit breaker is now OPEN
        assert breaker.state == BreakerState.OPEN
        assert breaker.is_available is False

        # --- Phase 2: Escalation fires ---
        states = {
            "api_gateway": {
                "consecutive_failures": breaker._failure_count,
                "last_error": "timeout #5",
            }
        }
        alerts = escalation.evaluate_triggers(states)
        assert len(alerts) == 1
        assert alerts[0].level == EscalationLevel.URGENT

        # Publish escalation event
        bus.publish(
            "failure.escalated",
            payload={"service": "api_gateway", "level": "URGENT", "message": alerts[0].message},
            source="escalation_engine",
            correlation_id=cid,
        )

        # Verify chain has all events
        chain = bus.get_chain(cid)
        assert chain is not None
        assert len(chain.event_ids) == 6  # 5 detections + 1 escalation
        assert chain.status == "in_progress"

        # --- Phase 3: Recovery after timeout ---
        with patch("bridge.circuit_breaker.time") as mock_time:
            mock_time.monotonic.return_value = breaker._last_failure_at + 3.0
            assert breaker.state == BreakerState.HALF_OPEN

        # Successful probe request
        breaker.record_success()
        assert breaker._state == BreakerState.CLOSED
        assert breaker._failure_count == 0

        # De-escalate
        recovered_states = {
            "api_gateway": {"consecutive_failures": 0, "last_error": None},
        }
        cleared = escalation.check_de_escalation(recovered_states)
        assert "api_gateway" in cleared

        # Publish recovery event
        bus.publish(
            "failure.recovered",
            payload={"service": "api_gateway"},
            source="health_check",
            correlation_id=cid,
        )
        bus.complete_chain(cid)

        # --- Verify final state ---
        chain = bus.get_chain(cid)
        assert chain.status == "completed"
        assert len(chain.event_ids) == 7  # 5 detections + 1 escalation + 1 recovery

        # All events were delivered to subscribers
        assert len(all_events) == 7

        # Breaker is healthy
        status = breaker.get_status()
        assert status["state"] == "closed"
        assert status["failure_count"] == 0
        assert status["total_trips"] == 1

    def test_cascade_with_multiple_services(self, tmp_path):
        """Multiple services can fail independently with isolated breakers and alerts."""
        registry = CircuitBreakerRegistry()
        escalation = EscalationEngine(state_dir=tmp_path)
        bus = EventBus(data_dir=tmp_path)

        # Service A: 5 failures -> URGENT
        breaker_a = registry.get("service_a", failure_threshold=5)
        for _ in range(5):
            breaker_a.record_failure(reason="timeout")

        # Service B: 3 failures -> NUDGE
        breaker_b = registry.get("service_b", failure_threshold=5)
        for _ in range(3):
            breaker_b.record_failure(reason="connection refused")

        assert breaker_a.state == BreakerState.OPEN
        assert breaker_b.state == BreakerState.CLOSED  # only 3, threshold is 5

        states = {
            "service_a": {"consecutive_failures": 5, "last_error": "timeout"},
            "service_b": {"consecutive_failures": 3, "last_error": "connection refused"},
        }

        alerts = escalation.evaluate_triggers(states)
        assert len(alerts) == 2

        levels = {a.source: a.level for a in alerts}
        assert levels["service_a"] == EscalationLevel.URGENT
        assert levels["service_b"] == EscalationLevel.NUDGE

        # Each gets its own correlation chain
        cid_a = bus.start_chain()
        cid_b = bus.start_chain()

        bus.publish("failure.escalated", payload={"service": "service_a"}, correlation_id=cid_a)
        bus.publish("failure.escalated", payload={"service": "service_b"}, correlation_id=cid_b)

        chain_a = bus.get_chain(cid_a)
        chain_b = bus.get_chain(cid_b)
        assert len(chain_a.event_ids) == 1
        assert len(chain_b.event_ids) == 1

        # Registry shows both breakers
        all_status = registry.get_all_status()
        assert len(all_status) == 2


# ---------------------------------------------------------------------------
# 8. Escalation state persistence round-trip
# ---------------------------------------------------------------------------

class TestEscalationPersistence:

    def test_save_and_load_preserves_active_alerts(self, tmp_path):
        """Active alerts survive a save/load cycle."""
        engine1 = EscalationEngine(state_dir=tmp_path)
        states = {
            "api_gateway": {"consecutive_failures": 5, "last_error": "timeout"},
        }
        alerts = engine1.evaluate_triggers(states)
        assert len(alerts) == 1
        engine1.save_state()

        # New engine instance loads persisted state
        engine2 = EscalationEngine(state_dir=tmp_path)
        engine2.load_state()

        # The alert source is still marked active, so a re-evaluation won't duplicate
        alerts_2 = engine2.evaluate_triggers(states)
        assert len(alerts_2) == 0, "Alert should already be active from loaded state"

        # De-escalation still works on the loaded alert
        recovered = {"api_gateway": {"consecutive_failures": 0}}
        cleared = engine2.check_de_escalation(recovered)
        assert "api_gateway" in cleared


# ---------------------------------------------------------------------------
# 9. Alert formatting
# ---------------------------------------------------------------------------

class TestAlertFormatting:

    def test_format_urgent_includes_mention_and_action(self, escalation):
        """URGENT alerts include operator mention and action-needed footer."""
        alert = ActiveAlert(
            source="api_gateway",
            level=EscalationLevel.URGENT,
            message="api_gateway has 5 consecutive failures: timeout",
            triggered_at=datetime.now(timezone.utc).isoformat(),
            last_notified_at=datetime.now(timezone.utc).isoformat(),
        )
        formatted = escalation.format_alert(alert)
        assert "<@operator>" in formatted
        assert "Action needed" in formatted
        assert "api_gateway" in formatted

    def test_format_nudge_uses_warning_prefix(self, escalation):
        """NUDGE alerts use a warning indicator."""
        alert = ActiveAlert(
            source="api_gateway",
            level=EscalationLevel.NUDGE,
            message="api_gateway has 3 failures",
            triggered_at=datetime.now(timezone.utc).isoformat(),
            last_notified_at=datetime.now(timezone.utc).isoformat(),
        )
        formatted = escalation.format_alert(alert)
        # Warning emoji prefix
        assert "\u26a0\ufe0f" in formatted
        assert "api_gateway" in formatted
