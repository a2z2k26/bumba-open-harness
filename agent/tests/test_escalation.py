"""Tests for MS2.5: Proactive Escalation Engine."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from bridge.escalation import ActiveAlert, EscalationEngine, EscalationLevel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_state(state_dir: Path, service: str, state: dict) -> Path:
    """Write a service state JSON file and return its path."""
    path = state_dir / f"{service}-state.json"
    path.write_text(json.dumps(state))
    return path


def _make_engine(tmp_path: Path, **kwargs) -> EscalationEngine:
    """Create an EscalationEngine pointed at tmp_path."""
    state_dir = tmp_path / "service_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return EscalationEngine(state_dir=state_dir, **kwargs)


# ---------------------------------------------------------------------------
# Level ordering
# ---------------------------------------------------------------------------

def test_level_ordering():
    """SILENCE < CASUAL < NUDGE < URGENT."""
    assert EscalationLevel.SILENCE < EscalationLevel.CASUAL
    assert EscalationLevel.CASUAL < EscalationLevel.NUDGE
    assert EscalationLevel.NUDGE < EscalationLevel.URGENT


# ---------------------------------------------------------------------------
# Trigger evaluation
# ---------------------------------------------------------------------------

def test_evaluate_3_failures_nudge(tmp_path: Path):
    """3 consecutive failures produces a NUDGE alert."""
    engine = _make_engine(tmp_path)
    states = {
        "briefing": {"consecutive_failures": 3, "last_error": "timeout"},
    }
    alerts = engine.evaluate_triggers(states)
    assert len(alerts) == 1
    assert alerts[0].level == EscalationLevel.NUDGE
    assert alerts[0].source == "briefing"
    assert "3 consecutive failures" in alerts[0].message


def test_evaluate_5_failures_urgent(tmp_path: Path):
    """5 consecutive failures produces an URGENT alert."""
    engine = _make_engine(tmp_path)
    states = {
        "checkin": {"consecutive_failures": 5, "last_error": "crash"},
    }
    alerts = engine.evaluate_triggers(states)
    assert len(alerts) == 1
    assert alerts[0].level == EscalationLevel.URGENT
    assert alerts[0].source == "checkin"


def test_evaluate_email_urgent_casual(tmp_path: Path):
    """has_urgent email state produces a CASUAL alert."""
    engine = _make_engine(tmp_path)
    states = {
        "email": {"consecutive_failures": 0, "has_urgent": True},
    }
    alerts = engine.evaluate_triggers(states)
    assert len(alerts) == 1
    assert alerts[0].level == EscalationLevel.CASUAL
    assert alerts[0].source == "email_urgent"


def test_evaluate_healthy_no_alerts(tmp_path: Path):
    """All-healthy states produce no alerts."""
    engine = _make_engine(tmp_path)
    states = {
        "briefing": {"consecutive_failures": 0, "last_error": None},
        "checkin": {"consecutive_failures": 0, "last_error": None},
        "email": {"consecutive_failures": 0, "has_urgent": False},
        "calendar": {"consecutive_failures": 0, "has_conflict": False},
    }
    alerts = engine.evaluate_triggers(states)
    assert len(alerts) == 0


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------

def test_cooldown_prevents_duplicate(tmp_path: Path):
    """Same source within 300s cooldown produces no new alert."""
    engine = _make_engine(tmp_path)
    states = {
        "briefing": {"consecutive_failures": 3, "last_error": "fail"},
    }

    # First evaluation — should fire
    alerts1 = engine.evaluate_triggers(states)
    assert len(alerts1) == 1

    # Clear active alert so cooldown (not active check) is the gate
    engine._active_alerts.clear()

    # Second evaluation within cooldown — should NOT fire
    alerts2 = engine.evaluate_triggers(states)
    assert len(alerts2) == 0


def test_cooldown_expired_allows_new(tmp_path: Path):
    """Same source after cooldown expires produces a new alert."""
    engine = _make_engine(tmp_path)
    states = {
        "briefing": {"consecutive_failures": 3, "last_error": "fail"},
    }

    # First evaluation
    alerts1 = engine.evaluate_triggers(states)
    assert len(alerts1) == 1

    # Clear active alert and push cooldown into the past
    engine._active_alerts.clear()
    engine._cooldowns["briefing"] = time.monotonic() - 301

    # Second evaluation after cooldown — should fire
    alerts2 = engine.evaluate_triggers(states)
    assert len(alerts2) == 1


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------

def _mock_now_et(hour: int):
    """Return a mock datetime.now that returns a given hour in US/Eastern."""
    eastern = ZoneInfo("US/Eastern")
    fake_dt = datetime(2026, 3, 13, hour, 30, 0, tzinfo=eastern)

    def side_effect(tz=None):
        if tz is not None:
            return fake_dt.astimezone(tz)
        return fake_dt

    return side_effect


def test_quiet_hours_defers_nudge(tmp_path: Path):
    """NUDGE during quiet hours (03:00 ET) is deferred."""
    engine = _make_engine(tmp_path)

    alert = ActiveAlert(
        source="briefing",
        level=EscalationLevel.NUDGE,
        message="test nudge",
        triggered_at="2026-03-13T08:00:00+00:00",
        last_notified_at="2026-03-13T08:00:00+00:00",
    )

    with patch("bridge.escalation.datetime") as mock_dt:
        mock_dt.now = _mock_now_et(3)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        deliver, defer = engine.apply_quiet_hours([alert])

    assert len(deliver) == 0
    assert len(defer) == 1
    assert defer[0].deferred is True


def test_quiet_hours_passes_urgent(tmp_path: Path):
    """URGENT during quiet hours still delivers immediately."""
    engine = _make_engine(tmp_path)

    alert = ActiveAlert(
        source="token_refresher",
        level=EscalationLevel.URGENT,
        message="token error",
        triggered_at="2026-03-13T08:00:00+00:00",
        last_notified_at="2026-03-13T08:00:00+00:00",
    )

    with patch("bridge.escalation.datetime") as mock_dt:
        mock_dt.now = _mock_now_et(3)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        deliver, defer = engine.apply_quiet_hours([alert])

    assert len(deliver) == 1
    assert len(defer) == 0
    assert deliver[0].level == EscalationLevel.URGENT


@pytest.mark.parametrize("hour", [7, 8])
def test_quiet_hours_includes_seven_and_eight_am(tmp_path: Path, hour: int):
    """7am and 8am ET are quiet (post-#2194 fix; pre-fix they were not)."""
    engine = _make_engine(tmp_path)

    with patch("bridge.escalation.datetime") as mock_dt:
        mock_dt.now = _mock_now_et(hour)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        assert engine.is_quiet_hours() is True


def test_quiet_hours_excludes_nine_am(tmp_path: Path):
    """9am ET is the post-quiet boundary — NOT quiet."""
    engine = _make_engine(tmp_path)

    with patch("bridge.escalation.datetime") as mock_dt:
        mock_dt.now = _mock_now_et(9)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        assert engine.is_quiet_hours() is False


def test_quiet_hours_excludes_midnight(tmp_path: Path):
    """Midnight (00:00 ET) is NOT quiet — quiet window starts at 01:00."""
    engine = _make_engine(tmp_path)

    with patch("bridge.escalation.datetime") as mock_dt:
        mock_dt.now = _mock_now_et(0)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        assert engine.is_quiet_hours() is False


def test_apply_quiet_hours_outside(tmp_path: Path):
    """Outside quiet hours (14:00 ET), all alerts deliver immediately."""
    engine = _make_engine(tmp_path)

    alerts = [
        ActiveAlert(
            source="svc1",
            level=EscalationLevel.NUDGE,
            message="nudge",
            triggered_at="2026-03-13T19:00:00+00:00",
            last_notified_at="2026-03-13T19:00:00+00:00",
        ),
        ActiveAlert(
            source="svc2",
            level=EscalationLevel.URGENT,
            message="urgent",
            triggered_at="2026-03-13T19:00:00+00:00",
            last_notified_at="2026-03-13T19:00:00+00:00",
        ),
    ]

    with patch("bridge.escalation.datetime") as mock_dt:
        mock_dt.now = _mock_now_et(14)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        deliver, defer = engine.apply_quiet_hours(alerts)

    assert len(deliver) == 2
    assert len(defer) == 0


# ---------------------------------------------------------------------------
# Flush deferred
# ---------------------------------------------------------------------------

def test_flush_deferred(tmp_path: Path):
    """Deferred alerts are returned and queue cleared on flush."""
    engine = _make_engine(tmp_path)

    alert = ActiveAlert(
        source="svc",
        level=EscalationLevel.NUDGE,
        message="deferred nudge",
        triggered_at="2026-03-13T08:00:00+00:00",
        last_notified_at="2026-03-13T08:00:00+00:00",
        deferred=True,
    )
    engine._deferred_queue.append(alert)

    flushed = engine.flush_deferred()
    assert len(flushed) == 1
    assert flushed[0].source == "svc"

    # Queue should now be empty
    assert len(engine.flush_deferred()) == 0


# ---------------------------------------------------------------------------
# De-escalation
# ---------------------------------------------------------------------------

def test_de_escalation_clears_active(tmp_path: Path):
    """Active alert cleared when consecutive_failures drops to 0."""
    engine = _make_engine(tmp_path)

    # Simulate an active alert
    engine._active_alerts["briefing"] = ActiveAlert(
        source="briefing",
        level=EscalationLevel.NUDGE,
        message="3 failures",
        triggered_at="2026-03-13T08:00:00+00:00",
        last_notified_at="2026-03-13T08:00:00+00:00",
    )

    states = {
        "briefing": {"consecutive_failures": 0, "last_error": None},
    }

    cleared = engine.check_de_escalation(states)
    assert "briefing" in cleared
    assert "briefing" not in engine._active_alerts


def test_de_escalation_keeps_active(tmp_path: Path):
    """Active alert stays when consecutive_failures is still >= 3."""
    engine = _make_engine(tmp_path)

    engine._active_alerts["briefing"] = ActiveAlert(
        source="briefing",
        level=EscalationLevel.NUDGE,
        message="3 failures",
        triggered_at="2026-03-13T08:00:00+00:00",
        last_notified_at="2026-03-13T08:00:00+00:00",
    )

    states = {
        "briefing": {"consecutive_failures": 3, "last_error": "still broken"},
    }

    cleared = engine.check_de_escalation(states)
    assert len(cleared) == 0
    assert "briefing" in engine._active_alerts


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def test_format_silence_empty(tmp_path: Path):
    """SILENCE level formats to empty string."""
    engine = _make_engine(tmp_path)
    alert = ActiveAlert(
        source="test",
        level=EscalationLevel.SILENCE,
        message="silent",
        triggered_at="2026-03-13T08:00:00+00:00",
        last_notified_at="2026-03-13T08:00:00+00:00",
    )
    assert engine.format_alert(alert) == ""


def test_format_urgent_has_mention(tmp_path: Path):
    """URGENT level includes operator mention."""
    engine = _make_engine(tmp_path, operator_mention="<@12345>")
    alert = ActiveAlert(
        source="token_refresher",
        level=EscalationLevel.URGENT,
        message="token error",
        triggered_at="2026-03-13T08:00:00+00:00",
        last_notified_at="2026-03-13T08:00:00+00:00",
    )
    formatted = engine.format_alert(alert)
    assert "<@12345>" in formatted
    assert "Action needed" in formatted
    assert "\U0001f6a8" in formatted


def test_format_casual(tmp_path: Path):
    """CASUAL level formats with info icon."""
    engine = _make_engine(tmp_path)
    alert = ActiveAlert(
        source="email_urgent",
        level=EscalationLevel.CASUAL,
        message="Urgent email detected",
        triggered_at="2026-03-13T08:00:00+00:00",
        last_notified_at="2026-03-13T08:00:00+00:00",
    )
    formatted = engine.format_alert(alert)
    assert "\u2139\ufe0f" in formatted
    assert "Urgent email" in formatted


def test_format_nudge(tmp_path: Path):
    """NUDGE level formats with warning icon."""
    engine = _make_engine(tmp_path)
    alert = ActiveAlert(
        source="svc",
        level=EscalationLevel.NUDGE,
        message="something wrong",
        triggered_at="2026-03-13T08:00:00+00:00",
        last_notified_at="2026-03-13T08:00:00+00:00",
    )
    formatted = engine.format_alert(alert)
    assert "\u26a0\ufe0f" in formatted


# ---------------------------------------------------------------------------
# Scan service states
# ---------------------------------------------------------------------------

def test_scan_service_states(tmp_path: Path):
    """Reads all *-state.json files from state_dir."""
    state_dir = tmp_path / "service_state"
    state_dir.mkdir(parents=True, exist_ok=True)

    # Write two state files
    _write_state(state_dir, "briefing", {"consecutive_failures": 0, "last_run": "2026-03-13T08:00:00"})
    _write_state(state_dir, "checkin", {"consecutive_failures": 2, "last_error": "timeout"})

    # Write a non-state file (should be ignored)
    (state_dir / "other.json").write_text("{}")

    engine = EscalationEngine(state_dir=state_dir)
    states = engine.scan_service_states()

    assert "briefing" in states
    assert "checkin" in states
    assert "other" not in states
    assert states["checkin"]["consecutive_failures"] == 2


# ---------------------------------------------------------------------------
# Save / Load state persistence
# ---------------------------------------------------------------------------

def test_save_load_state(tmp_path: Path):
    """Persist and reload active alerts."""
    state_dir = tmp_path / "service_state"
    state_dir.mkdir(parents=True, exist_ok=True)

    engine = EscalationEngine(state_dir=state_dir, operator_mention="<@op>")

    # Create active alert and cooldown
    alert = ActiveAlert(
        source="briefing",
        level=EscalationLevel.NUDGE,
        message="3 failures",
        triggered_at="2026-03-13T08:00:00+00:00",
        last_notified_at="2026-03-13T08:00:00+00:00",
    )
    engine._active_alerts["briefing"] = alert
    engine._cooldowns["briefing"] = time.monotonic()

    # Save
    engine.save_state()

    # Verify file exists
    state_file = state_dir / "escalation-state.json"
    assert state_file.exists()

    # Load into a new engine
    engine2 = EscalationEngine(state_dir=state_dir, operator_mention="<@op>")
    engine2.load_state()

    assert "briefing" in engine2._active_alerts
    assert engine2._active_alerts["briefing"].level == EscalationLevel.NUDGE
    assert engine2._active_alerts["briefing"].message == "3 failures"
    assert "briefing" in engine2._cooldowns


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------

def test_disk_usage_nudge(tmp_path: Path):
    """Disk usage > 90 but <= 95 produces NUDGE."""
    engine = _make_engine(tmp_path)
    states = {"disk": {"disk_usage_pct": 92}}
    alerts = engine.evaluate_triggers(states)
    assert len(alerts) == 1
    assert alerts[0].level == EscalationLevel.NUDGE
    assert "92%" in alerts[0].message


def test_disk_usage_urgent(tmp_path: Path):
    """Disk usage > 95 produces URGENT."""
    engine = _make_engine(tmp_path)
    states = {"disk": {"disk_usage_pct": 97}}
    alerts = engine.evaluate_triggers(states)
    assert len(alerts) == 1
    assert alerts[0].level == EscalationLevel.URGENT
    assert "97%" in alerts[0].message


def test_token_refresher_error_urgent(tmp_path: Path):
    """Token refresher with last_error produces URGENT."""
    engine = _make_engine(tmp_path)
    states = {"token_refresher": {"last_error": "403 Forbidden", "consecutive_failures": 0}}
    alerts = engine.evaluate_triggers(states)
    assert len(alerts) == 1
    assert alerts[0].level == EscalationLevel.URGENT
    assert "403 Forbidden" in alerts[0].message


def test_calendar_conflict_casual(tmp_path: Path):
    """Calendar conflict produces CASUAL alert."""
    engine = _make_engine(tmp_path)
    states = {"calendar": {"consecutive_failures": 0, "has_conflict": True}}
    alerts = engine.evaluate_triggers(states)
    assert len(alerts) == 1
    assert alerts[0].level == EscalationLevel.CASUAL
    assert alerts[0].source == "calendar_conflict"


# ---------------------------------------------------------------------------
# Stale service detection
# ---------------------------------------------------------------------------

def test_stale_service_nudge(tmp_path: Path):
    """Service that hasn't run in 2x its expected interval triggers NUDGE."""
    engine = _make_engine(tmp_path)
    # job_search_execute has 7200s (2h) expected interval
    # Set last_run to 5 hours ago → 2x exceeded
    stale_time = (datetime.now(timezone.utc).timestamp() - 18000)  # 5h ago
    stale_iso = datetime.fromtimestamp(stale_time, tz=timezone.utc).isoformat()
    states = {
        "job_search_execute": {
            "consecutive_failures": 0,
            "last_run": stale_iso,
        },
    }
    alerts = engine.evaluate_triggers(states)
    stale_alerts = [a for a in alerts if a.source == "job_search_execute_stale"]
    assert len(stale_alerts) == 1
    assert stale_alerts[0].level == EscalationLevel.NUDGE
    assert "hasn't run" in stale_alerts[0].message


def test_fresh_service_no_stale_alert(tmp_path: Path):
    """Service that ran recently does not trigger stale alert."""
    engine = _make_engine(tmp_path)
    recent_iso = datetime.now(timezone.utc).isoformat()
    states = {
        "job_search_execute": {
            "consecutive_failures": 0,
            "last_run": recent_iso,
        },
    }
    alerts = engine.evaluate_triggers(states)
    stale_alerts = [a for a in alerts if a.source.endswith("_stale")]
    assert len(stale_alerts) == 0


def test_stale_detection_tolerates_naive_timestamp(tmp_path: Path):
    """Naive ISO timestamps in state files don't crash the scan.

    Regression for the runtime warning observed 2026-05-15:
    ``Escalation scan failed: can't compare offset-naive and offset-aware
    datetimes``. State files written by older code (or any non-services
    writer) may contain naive ISO strings. The scan must normalize to
    UTC-aware before subtraction — a TypeError here silently kills the
    entire escalation tick (every service in the loop is skipped).
    """
    engine = _make_engine(tmp_path)
    # 5h ago, written WITHOUT timezone info — the failure-mode source.
    # Construct directly (instead of utcnow()) to avoid the deprecation
    # warning — the naivety here is intentional, simulating a state file
    # written by older code.
    naive_stale = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    naive_stale_iso = naive_stale.isoformat()  # No "+00:00" suffix
    assert "+" not in naive_stale_iso  # Confirm test setup is naive
    states = {
        "job_search_execute": {
            "consecutive_failures": 0,
            "last_run": naive_stale_iso,
        },
    }
    # Pre-fix this raised TypeError caught by background_loops and
    # logged as "Escalation scan failed". Post-fix it returns alerts
    # cleanly (the naive timestamp will be ~now, so no stale alert,
    # but the important assertion is "no crash").
    alerts = engine.evaluate_triggers(states)
    assert isinstance(alerts, list)  # Did not raise


def test_stale_detection_tolerates_mixed_naive_and_aware_activity(
    tmp_path: Path,
):
    """Mixed legacy naive and new aware activity fields must not crash."""
    engine = _make_engine(tmp_path)
    now = datetime.now(timezone.utc)
    states = {
        "checkin": {
            "consecutive_failures": 0,
            "last_run": now.replace(tzinfo=None, microsecond=0).isoformat(),
            "last_skipped_at": now.isoformat(),
        },
    }

    alerts = engine.evaluate_triggers(states)
    assert isinstance(alerts, list)


def test_stale_service_de_escalates(tmp_path: Path):
    """Stale alert clears when service runs again."""
    engine = _make_engine(tmp_path)

    engine._active_alerts["job_search_execute_stale"] = ActiveAlert(
        source="job_search_execute_stale",
        level=EscalationLevel.NUDGE,
        message="stale",
        triggered_at="2026-03-13T08:00:00+00:00",
        last_notified_at="2026-03-13T08:00:00+00:00",
    )

    recent_iso = datetime.now(timezone.utc).isoformat()
    states = {
        "job_search_execute": {
            "consecutive_failures": 0,
            "last_run": recent_iso,
        },
    }

    cleared = engine.check_de_escalation(states)
    assert "job_search_execute_stale" in cleared


def test_stale_service_de_escalates_with_naive_recent_activity(
    tmp_path: Path,
):
    """Legacy naive timestamps must not crash stale-alert clearing."""
    engine = _make_engine(tmp_path)

    engine._active_alerts["job_search_execute_stale"] = ActiveAlert(
        source="job_search_execute_stale",
        level=EscalationLevel.NUDGE,
        message="stale",
        triggered_at="2026-03-13T08:00:00+00:00",
        last_notified_at="2026-03-13T08:00:00+00:00",
    )

    recent_naive_iso = (
        datetime.now(timezone.utc)
        .replace(tzinfo=None, microsecond=0)
        .isoformat()
    )
    states = {
        "job_search_execute": {
            "consecutive_failures": 0,
            "last_run": recent_naive_iso,
        },
    }

    cleared = engine.check_de_escalation(states)
    assert "job_search_execute_stale" in cleared


# ---------------------------------------------------------------------------
# #1683 — last_skipped_at counts as activity for staleness detection
# ---------------------------------------------------------------------------

def test_recent_skip_prevents_stale_alert(tmp_path: Path):
    """#1683: a service with stale last_run but recent last_skipped_at is NOT stale.

    Reproduces the #1615 failure mode for checkin: hourly cron correctly
    skips during active operator windows, never advancing last_run. The
    staleness check must consult last_skipped_at to avoid a false alarm.
    """
    engine = _make_engine(tmp_path)
    # checkin has 43200s (12h) expected interval; 25h ago would trip at 2x=24h
    now = datetime.now(timezone.utc)
    stale_run = (now.timestamp() - 25 * 3600)
    fresh_skip = (now.timestamp() - 3600)  # 1h ago
    states = {
        "checkin": {
            "consecutive_failures": 0,
            "last_run": datetime.fromtimestamp(stale_run, tz=timezone.utc).isoformat(),
            "last_skipped_at": datetime.fromtimestamp(fresh_skip, tz=timezone.utc).isoformat(),
        },
    }
    alerts = engine.evaluate_triggers(states)
    stale_alerts = [a for a in alerts if a.source.endswith("_stale")]
    assert stale_alerts == [], (
        f"recent last_skipped_at should suppress stale alert; got {stale_alerts}"
    )


def test_stale_run_and_stale_skip_still_trips(tmp_path: Path):
    """#1683 pair: when BOTH last_run and last_skipped_at are stale, alert fires."""
    engine = _make_engine(tmp_path)
    now = datetime.now(timezone.utc)
    stale_iso = datetime.fromtimestamp(now.timestamp() - 25 * 3600, tz=timezone.utc).isoformat()
    states = {
        "checkin": {
            "consecutive_failures": 0,
            "last_run": stale_iso,
            "last_skipped_at": stale_iso,
        },
    }
    alerts = engine.evaluate_triggers(states)
    stale_alerts = [a for a in alerts if a.source == "checkin_stale"]
    assert len(stale_alerts) == 1
    assert stale_alerts[0].level == EscalationLevel.NUDGE


def test_brand_new_service_no_stale_alert(tmp_path: Path):
    """#1683: a state with all three activity fields None/missing produces no stale alert.

    Preserves existing behavior: services that have never run (e.g., just
    after a fresh deploy) should not trip the stale check.
    """
    engine = _make_engine(tmp_path)
    states = {
        "checkin": {
            "consecutive_failures": 0,
            "last_run": None,
            "last_success_time": None,
            "last_skipped_at": None,
        },
    }
    alerts = engine.evaluate_triggers(states)
    stale_alerts = [a for a in alerts if a.source.endswith("_stale")]
    assert stale_alerts == []


def test_skip_only_service_uses_skip_as_activity(tmp_path: Path):
    """#1683: a service that has only ever skipped (last_run=None) uses last_skipped_at.

    Real-world shape for checkin during a long uninterrupted active window:
    plist fires hourly, every run returns SILENCE, last_run never advances
    from None. last_skipped_at is the only signal of liveness.
    """
    engine = _make_engine(tmp_path)
    fresh_skip_iso = datetime.now(timezone.utc).isoformat()
    states = {
        "checkin": {
            "consecutive_failures": 0,
            "last_run": None,
            "last_skipped_at": fresh_skip_iso,
        },
    }
    alerts = engine.evaluate_triggers(states)
    stale_alerts = [a for a in alerts if a.source.endswith("_stale")]
    assert stale_alerts == []


def test_recent_skip_de_escalates_existing_stale_alert(tmp_path: Path):
    """#1683: a recent last_skipped_at clears an already-active stale alert."""
    engine = _make_engine(tmp_path)

    engine._active_alerts["checkin_stale"] = ActiveAlert(
        source="checkin_stale",
        level=EscalationLevel.NUDGE,
        message="stale",
        triggered_at="2026-03-13T08:00:00+00:00",
        last_notified_at="2026-03-13T08:00:00+00:00",
    )

    fresh_skip_iso = datetime.now(timezone.utc).isoformat()
    states = {
        "checkin": {
            "consecutive_failures": 0,
            "last_run": None,
            "last_skipped_at": fresh_skip_iso,
        },
    }

    cleared = engine.check_de_escalation(states)
    assert "checkin_stale" in cleared


# ---------------------------------------------------------------------------
# Sprint D2.4 — CASUAL first-failure trigger
# ---------------------------------------------------------------------------

def test_casual_fires_at_1_not_2(tmp_path: Path):
    """CASUAL fires at consecutive_failures == 1, not at 2 (no trigger for 2)."""
    engine = _make_engine(tmp_path)

    # 1 failure -> CASUAL
    states = {"briefing": {"consecutive_failures": 1, "last_error": "timeout"}}
    alerts = engine.evaluate_triggers(states)
    assert len(alerts) == 1
    assert alerts[0].level == EscalationLevel.CASUAL
    assert alerts[0].source == "briefing_casual"
    assert "failed once" in alerts[0].message

    # 2 failures -> no alert (above CASUAL threshold, below NUDGE threshold)
    engine2 = _make_engine(tmp_path)
    states2 = {"checkin": {"consecutive_failures": 2, "last_error": "boom"}}
    alerts2 = engine2.evaluate_triggers(states2)
    assert len(alerts2) == 0


def test_casual_respects_1h_cooldown(tmp_path: Path):
    """Second CASUAL evaluation within 1h cooldown must not re-fire."""
    engine = _make_engine(tmp_path)
    states = {"briefing": {"consecutive_failures": 1, "last_error": "first"}}

    first = engine.evaluate_triggers(states)
    assert any(a.level == EscalationLevel.CASUAL for a in first), "first eval must fire"

    # Clear active alert so cooldown (not active-alert gate) is tested
    engine._active_alerts.pop("briefing_casual", None)

    second = engine.evaluate_triggers(states)
    assert not any(a.level == EscalationLevel.CASUAL for a in second), (
        "second eval inside 1h cooldown must not re-fire"
    )


def test_casual_de_escalates_on_recovery(tmp_path: Path):
    """CASUAL alert for briefing_casual clears when consecutive_failures returns to 0."""
    engine = _make_engine(tmp_path)

    # Inject active CASUAL alert
    engine._active_alerts["briefing_casual"] = ActiveAlert(
        source="briefing_casual",
        level=EscalationLevel.CASUAL,
        message="briefing failed once: timeout",
        triggered_at="2026-05-03T08:00:00+00:00",
        last_notified_at="2026-05-03T08:00:00+00:00",
    )

    states = {"briefing": {"consecutive_failures": 0, "last_error": None}}
    cleared = engine.check_de_escalation(states)
    assert "briefing_casual" in cleared
    assert "briefing_casual" not in engine._active_alerts


def test_quiet_hours_suppress_casual(tmp_path: Path):
    """CASUAL alert during quiet hours passes through (CASUAL is not deferred)."""
    engine = _make_engine(tmp_path)

    alert = ActiveAlert(
        source="briefing_casual",
        level=EscalationLevel.CASUAL,
        message="briefing failed once: timeout",
        triggered_at="2026-05-03T03:00:00+00:00",
        last_notified_at="2026-05-03T03:00:00+00:00",
    )

    with patch("bridge.escalation.datetime") as mock_dt:
        mock_dt.now = _mock_now_et(3)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        deliver, defer = engine.apply_quiet_hours([alert])

    # CASUAL passes through (not deferred) even during quiet hours
    assert len(deliver) == 1
    assert deliver[0].level == EscalationLevel.CASUAL
    assert len(defer) == 0


def test_full_chain_smoke(tmp_path: Path):
    """End-to-end: 1→3→5 failures produce CASUAL→NUDGE→URGENT; recovery de-escalates."""
    state_dir = tmp_path / "chain_state"
    state_dir.mkdir()
    engine = EscalationEngine(state_dir=state_dir)

    def write_state(failures: int, error: str = "boom") -> None:
        (state_dir / "demo-state.json").write_text(
            json.dumps({"consecutive_failures": failures, "last_error": error})
        )

    # 1 failure -> CASUAL
    write_state(1)
    alerts = engine.evaluate_triggers(engine.scan_service_states())
    assert any(
        a.level == EscalationLevel.CASUAL and a.source == "demo_casual"
        for a in alerts
    ), f"Expected CASUAL at 1 failure; got {alerts}"

    # 3 failures -> NUDGE (CASUAL still in cooldown, not re-fired)
    write_state(3)
    alerts = engine.evaluate_triggers(engine.scan_service_states())
    assert any(
        a.level == EscalationLevel.NUDGE and a.source == "demo"
        for a in alerts
    ), f"Expected NUDGE at 3 failures; got {alerts}"

    # 5 failures -> URGENT (NUDGE already active, URGENT fires with same source key)
    # Clear NUDGE active alert and cooldown so URGENT can fire
    engine._active_alerts.pop("demo", None)
    engine._cooldowns.pop("demo", None)
    write_state(5)
    alerts = engine.evaluate_triggers(engine.scan_service_states())
    assert any(
        a.level == EscalationLevel.URGENT and a.source == "demo"
        for a in alerts
    ), f"Expected URGENT at 5 failures; got {alerts}"

    # Recovery -> de-escalation
    engine._active_alerts["demo"] = ActiveAlert(
        source="demo",
        level=EscalationLevel.URGENT,
        message="5 failures",
        triggered_at="2026-05-03T08:00:00+00:00",
        last_notified_at="2026-05-03T08:00:00+00:00",
    )
    write_state(0)
    cleared = engine.check_de_escalation(engine.scan_service_states())
    assert "demo" in cleared, f"Expected demo to be cleared; cleared={cleared}"
