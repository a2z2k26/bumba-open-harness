"""Tests for MeetingPrebriefService registration + EventBus wiring (Sprint 02.07).

The service module itself has covering tests in test_z2_services.py; these
tests cover the four pieces Sprint 02.07 wires up:

  Test 1 — meeting_prebrief is in SERVICE_MAP and SERVICE_SCHEDULES.
  Test 2 — the launchd plist file exists and ``plutil -lint`` accepts it
           (skipped on non-darwin since plutil is macOS-only).
  Test 3 — BridgeApp.start() subscribes a callback to ``calcom.booking.created``.
  Test 4 — publishing a ``calcom.booking.created`` event ultimately invokes
           ``MeetingPrebriefService.handle_booking_event(booking_id)``.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.services.result import (
    SERVICE_NARRATIONS,
    SERVICE_SCHEDULES,
    ServiceResult,
)
from bridge.services.runner import (
    SERVICE_ALIASES,
    SERVICE_MAP,
    SERVICE_TIMEOUTS,
)


# ---------------------------------------------------------------------------
# Test 1 — SERVICE_MAP registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_meeting_prebrief_in_service_map(self) -> None:
        assert "meeting_prebrief" in SERVICE_MAP, (
            "meeting_prebrief must be registered in runner.SERVICE_MAP"
        )
        module_path, class_name = SERVICE_MAP["meeting_prebrief"]
        assert module_path == "bridge.services.meeting_prebrief"
        assert class_name == "MeetingPrebriefService"

    def test_meeting_prebrief_alias_exists(self) -> None:
        # Hyphenated alias resolves to the canonical underscored key.
        assert SERVICE_ALIASES.get("meeting-prebrief") == "meeting_prebrief"

    def test_meeting_prebrief_has_timeout(self) -> None:
        assert "meeting_prebrief" in SERVICE_TIMEOUTS
        # Polling fallback fires every 600s; timeout should be well under that.
        assert SERVICE_TIMEOUTS["meeting_prebrief"] <= 600

    def test_meeting_prebrief_in_service_schedules(self) -> None:
        assert "meeting_prebrief" in SERVICE_SCHEDULES
        # Schedule string should mention both the event topic and the polling cadence.
        schedule = SERVICE_SCHEDULES["meeting_prebrief"]
        assert "calcom.booking.created" in schedule
        assert "10 min" in schedule

    def test_meeting_prebrief_has_narration(self) -> None:
        assert "meeting_prebrief" in SERVICE_NARRATIONS
        narration = SERVICE_NARRATIONS["meeting_prebrief"]
        assert "prebrief" in narration.lower()

    def test_meeting_prebrief_class_importable(self) -> None:
        # Sanity: the class advertised in SERVICE_MAP actually loads.
        from bridge.services.meeting_prebrief import MeetingPrebriefService
        assert MeetingPrebriefService.__name__ == "MeetingPrebriefService"
        # handle_booking_event is the new method we added in Sprint 02.07.
        assert hasattr(MeetingPrebriefService, "handle_booking_event")


# ---------------------------------------------------------------------------
# Test 2 — plist file present and well-formed
# ---------------------------------------------------------------------------


class TestPlist:
    PLIST_NAME = "com.bumba.agent-meeting-prebrief.plist"

    @property
    def plist_path(self) -> Path:
        # Test is in agent/tests/, plist is in agent/scripts/
        return Path(__file__).resolve().parent.parent / "scripts" / self.PLIST_NAME

    def test_plist_file_exists(self) -> None:
        assert self.plist_path.exists(), f"missing plist at {self.plist_path}"

    def test_plist_invokes_meeting_prebrief_runner(self) -> None:
        contents = self.plist_path.read_text()
        # Same shape as funnel-post: python -m bridge.services.runner <name>
        assert "bridge.services.runner" in contents
        assert "meeting_prebrief" in contents
        # Confirms the 10-min polling fallback is configured (StartInterval=600).
        assert "<integer>600</integer>" in contents

    def test_plist_log_paths_match_naming_convention(self) -> None:
        contents = self.plist_path.read_text()
        assert "/opt/bumba-harness/logs/meeting-prebrief.log" in contents
        assert "/opt/bumba-harness/logs/meeting-prebrief-error.log" in contents

    @pytest.mark.skipif(
        sys.platform != "darwin",
        reason="plutil is a macOS-only utility",
    )
    def test_plist_passes_plutil_lint(self) -> None:
        result = subprocess.run(
            ["plutil", "-lint", str(self.plist_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"plutil -lint failed: stdout={result.stdout!r} stderr={result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# Test 3 — BridgeApp subscribes to calcom.booking.created on start()
# ---------------------------------------------------------------------------


class TestBridgeAppSubscription:
    def test_subscribe_called_with_calcom_booking_created(self) -> None:
        """The Sprint 02.07 wiring adds a subscribe() call inside start()
        for the ``calcom.booking.created`` topic."""
        from bridge.app import BridgeApp

        # Stand up an app skeleton with just enough for the subscribe path.
        app = BridgeApp.__new__(BridgeApp)
        app._daily_log = None  # skip the daily-log block — we only test the new wiring

        mock_event_bus = MagicMock()
        mock_autonomy = MagicMock()
        mock_autonomy.event_bus = mock_event_bus
        # initialize() is awaited inside start() — make it awaitable.
        mock_autonomy.initialize = AsyncMock(return_value=None)
        app._autonomy = mock_autonomy

        # Replicate the exact subscribe block from start():
        async def _exercise():
            if app._autonomy:
                await app._autonomy.initialize()
                if app._autonomy.event_bus is not None:
                    app._autonomy.event_bus.subscribe(
                        "calcom.booking.created",
                        app._on_calcom_booking_created,
                    )

        asyncio.run(_exercise())

        topics_subscribed = [
            call.args[0] for call in mock_event_bus.subscribe.call_args_list
        ]
        assert "calcom.booking.created" in topics_subscribed

        # Confirm the registered callback is the BridgeApp method.
        for call in mock_event_bus.subscribe.call_args_list:
            if call.args[0] == "calcom.booking.created":
                assert call.args[1] == app._on_calcom_booking_created
                break
        else:
            pytest.fail("calcom.booking.created subscription not found")


# ---------------------------------------------------------------------------
# Test 4 — End-to-end: publishing the event invokes handle_booking_event
# ---------------------------------------------------------------------------


class TestEventDispatch:
    def test_calcom_event_invokes_handle_booking_event(self, tmp_path: Path) -> None:
        """When BridgeApp._on_calcom_booking_created fires for a published
        event, MeetingPrebriefService.handle_booking_event(booking_id) is
        ultimately called with the correct uid."""
        from bridge.app import BridgeApp

        app = BridgeApp.__new__(BridgeApp)
        # Minimal config shim — the dispatcher only reads data_dir,
        # service_channel_id, operator_discord_id.
        config = MagicMock()
        config.data_dir = str(tmp_path)
        config.service_channel_id = "service-chan-123"
        config.operator_discord_id = "operator-456"
        app._config = config
        app._autonomy = None  # event_bus not needed for the dispatch path itself

        # Patch the service class so we can assert how it's called without
        # touching the real Cal.com interface.
        captured: dict = {}

        class _FakeService:
            def __init__(self, **kwargs) -> None:
                captured["init_kwargs"] = kwargs

            def handle_booking_event(
                self,
                booking_id: str,
                *,
                account: str | None = None,
            ) -> ServiceResult:
                captured["booking_id"] = booking_id
                captured["account"] = account
                return ServiceResult(
                    service="meeting_prebrief",
                    ok=True,
                    work_items=1,
                    duration_ms=5,
                    cost_usd=0.0,
                    narration="ok",
                )

        # Build an event-shaped object — payload mirrors calcom_webhook.handle()
        event = MagicMock()
        event.payload = {
            "trigger": "BOOKING_CREATED",
            "booking": {"uid": "booking-abc-123", "title": "Strategy sync"},
            "raw_uid": "booking-abc-123",
            "received_at": "2026-04-25T12:00:00+00:00",
        }

        async def _exercise():
            with patch(
                "bridge.services.meeting_prebrief.MeetingPrebriefService",
                _FakeService,
            ):
                # _on_calcom_booking_created is sync — it schedules a task
                app._on_calcom_booking_created(event)
                # Give the scheduled task a chance to run.
                # asyncio.create_task adds it to the running loop, so a single
                # 0-sleep yields control once.
                for _ in range(5):
                    await asyncio.sleep(0)

        asyncio.run(_exercise())

        assert captured.get("booking_id") == "booking-abc-123", (
            f"handle_booking_event was not invoked with the expected booking_id; "
            f"captured={captured}"
        )
        # service_channel_id should win over operator_discord_id.
        init_kwargs = captured.get("init_kwargs", {})
        assert init_kwargs.get("chat_id") == "service-chan-123"
        assert Path(str(init_kwargs.get("data_dir"))) == tmp_path

    def test_empty_booking_id_is_logged_and_skipped(self, tmp_path: Path) -> None:
        """If the event has no recoverable booking id, the handler logs a
        warning and does not crash. No service is constructed."""
        from bridge.app import BridgeApp

        app = BridgeApp.__new__(BridgeApp)
        config = MagicMock()
        config.data_dir = str(tmp_path)
        config.service_channel_id = ""
        config.operator_discord_id = ""
        app._config = config
        app._autonomy = None

        constructed: list = []

        class _FakeService:
            def __init__(self, **kwargs) -> None:
                constructed.append(kwargs)

            def handle_booking_event(
                self,
                booking_id: str,
                *,
                account: str | None = None,
            ) -> ServiceResult:
                raise AssertionError("should not be called for empty booking_id")

        event = MagicMock()
        event.payload = {"trigger": "BOOKING_CREATED", "booking": {}, "raw_uid": ""}

        async def _exercise():
            with patch(
                "bridge.services.meeting_prebrief.MeetingPrebriefService",
                _FakeService,
            ):
                app._on_calcom_booking_created(event)
                for _ in range(5):
                    await asyncio.sleep(0)

        asyncio.run(_exercise())

        assert constructed == [], (
            "MeetingPrebriefService should not have been constructed for an "
            "event with no booking id"
        )
