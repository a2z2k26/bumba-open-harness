"""Tests for Z2 services sprint: #498-#503.

Covers:
  - ServiceDispatchAdapter (S3.1 / #498)
  - RetroService Strategy routing flag (S3.2 / #499)
  - CalcomWebhookHandler (S4.1 / #500)
  - MeetingPrebriefService (S4.2+S5.1 / #501+#503)
  - ServiceBase narration helpers (S4.3 / #502)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# #498 — ServiceDispatchAdapter
# ---------------------------------------------------------------------------

class TestServiceDispatchAdapter:
    """Tests for bridge.services.dispatch_adapter.ServiceDispatchAdapter."""

    def _make_team_result(self, **kwargs):
        """Build a minimal TeamResult-like object."""
        defaults = {
            "department": "strategy",
            "manager_output": "EOD memo content",
            "employee_results": (),
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "duration_seconds": 1.0,
            "success": True,
            "error": None,
        }
        defaults.update(kwargs)
        obj = MagicMock()
        for k, v in defaults.items():
            setattr(obj, k, v)
        return obj

    def _make_deps(self):
        dep = MagicMock()
        dep.cost_limit_usd = 2.0
        return dep

    @pytest.mark.asyncio
    async def test_synthesize_calls_registry(self):
        """Adapter.synthesize calls registry.route and returns SynthesisResult."""
        from bridge.services.dispatch_adapter import ServiceDispatchAdapter

        team_result = self._make_team_result(manager_output="EOD memo content")
        registry = MagicMock()
        registry.route = AsyncMock(return_value=team_result)

        deps = self._make_deps()
        adapter = ServiceDispatchAdapter(registry)
        result = await adapter.synthesize("strategy", "compose EOD memo", deps)

        registry.route.assert_awaited_once()
        call_args = registry.route.call_args
        assert call_args[0][0] == "strategy"
        assert call_args[0][1] == "compose EOD memo"
        assert call_args[0][2] is deps
        assert result.manager_output == "EOD memo content"
        assert result.success is True
        assert result.error is None

    @pytest.mark.asyncio
    async def test_synthesize_passes_cost_and_duration(self):
        """Adapter propagates cost_usd and duration_s from TeamResult."""
        from bridge.services.dispatch_adapter import ServiceDispatchAdapter

        team_result = self._make_team_result(
            total_cost_usd=0.42,
            duration_seconds=18.0,
        )
        registry = MagicMock()
        registry.route = AsyncMock(return_value=team_result)

        adapter = ServiceDispatchAdapter(registry)
        result = await adapter.synthesize("strategy", "task", self._make_deps())

        assert result.cost_usd == pytest.approx(0.42, abs=0.001)
        assert result.duration_s >= 0.0

    @pytest.mark.asyncio
    async def test_synthesize_propagates_failure(self):
        """Adapter returns success=False when TeamResult.success is False."""
        from bridge.services.dispatch_adapter import ServiceDispatchAdapter

        team_result = self._make_team_result(
            success=False,
            error="cost_cap_exceeded",
            manager_output="",
        )
        registry = MagicMock()
        registry.route = AsyncMock(return_value=team_result)

        adapter = ServiceDispatchAdapter(registry)
        result = await adapter.synthesize("strategy", "task", self._make_deps())

        assert result.success is False
        assert result.error == "cost_cap_exceeded"

    @pytest.mark.asyncio
    async def test_synthesize_catches_exception(self):
        """Adapter catches registry exceptions and returns success=False."""
        from bridge.services.dispatch_adapter import ServiceDispatchAdapter

        registry = MagicMock()
        registry.route = AsyncMock(side_effect=RuntimeError("network error"))

        adapter = ServiceDispatchAdapter(registry)
        result = await adapter.synthesize("strategy", "task", self._make_deps())

        assert result.success is False
        assert "network error" in (result.error or "")
        assert result.manager_output == ""

    @pytest.mark.asyncio
    async def test_synthesize_none_manager_output_normalised(self):
        """adapter returns manager_output='' when TeamResult.manager_output is None."""
        from bridge.services.dispatch_adapter import ServiceDispatchAdapter

        team_result = self._make_team_result(manager_output=None)
        registry = MagicMock()
        registry.route = AsyncMock(return_value=team_result)

        adapter = ServiceDispatchAdapter(registry)
        result = await adapter.synthesize("strategy", "task", self._make_deps())

        assert result.manager_output == ""

    @pytest.mark.asyncio
    async def test_disabled_factory(self):
        """ServiceDispatchAdapter.disabled() returns a no-op adapter."""
        from bridge.services.dispatch_adapter import ServiceDispatchAdapter

        adapter = ServiceDispatchAdapter.disabled()
        result = await adapter.synthesize("strategy", "task", self._make_deps())

        assert result.success is False
        assert result.manager_output == ""


# ---------------------------------------------------------------------------
# #499 — RetroService Strategy flag
# ---------------------------------------------------------------------------

class TestRetroServiceStrategyFlag:
    """Tests for Z2-S3.2 Strategy routing in RetroService."""

    def _make_db(self, tmp_dir: Path) -> Path:
        db_path = tmp_dir / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""CREATE TABLE knowledge (
            key TEXT PRIMARY KEY, value TEXT, tags TEXT,
            source TEXT DEFAULT 'agent',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            archived INTEGER DEFAULT 0,
            category TEXT DEFAULT 'reference',
            salience REAL DEFAULT 1.0
        )""")
        conn.execute("""CREATE TABLE conversations (
            id INTEGER PRIMARY KEY, session_id TEXT, chat_id TEXT,
            role TEXT, content TEXT, created_at TEXT DEFAULT (datetime('now'))
        )""")
        conn.execute("""CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY, timestamp TEXT DEFAULT (datetime('now')),
            event_type TEXT, tool_name TEXT, arguments TEXT, outcome TEXT, details TEXT,
            session_id TEXT, chat_id TEXT
        )""")
        conn.execute("""CREATE TABLE message_queue (
            id INTEGER PRIMARY KEY, status TEXT DEFAULT 'pending',
            platform_message_id INTEGER, chat_id TEXT, text TEXT,
            received_at TEXT DEFAULT (datetime('now'))
        )""")
        conn.commit()
        conn.close()
        return db_path

    def test_compile_returns_string(self, tmp_dir):
        """RetroService.compile() returns a non-empty string."""
        from bridge.services.retro import RetroService

        db = self._make_db(tmp_dir)
        svc = RetroService(tmp_dir, db, "channel123")
        text = svc.compile()
        assert isinstance(text, str)
        assert len(text) > 0

    def test_flag_default_off(self, tmp_dir, monkeypatch):
        """ZONE2_RETRO_VIA_STRATEGY is off by default."""
        from bridge.services.retro import _strategy_flag_enabled
        monkeypatch.delenv("ZONE2_RETRO_VIA_STRATEGY", raising=False)
        assert _strategy_flag_enabled() is False

    def test_flag_on(self, tmp_dir, monkeypatch):
        """ZONE2_RETRO_VIA_STRATEGY=true enables the flag."""
        from bridge.services.retro import _strategy_flag_enabled
        monkeypatch.setenv("ZONE2_RETRO_VIA_STRATEGY", "true")
        assert _strategy_flag_enabled() is True

    def test_flag_off_uses_direct_render(self, tmp_dir, monkeypatch):
        """With flag off, no adapter is called even if one is injected."""
        from bridge.services.retro import RetroService

        monkeypatch.delenv("ZONE2_RETRO_VIA_STRATEGY", raising=False)
        db = self._make_db(tmp_dir)

        mock_adapter = MagicMock()
        svc = RetroService(
            tmp_dir, db, "channel123",
            dispatch_adapter=mock_adapter,
            delivery_hour=0,  # always in window
            delivery_minute=0,
        )
        # Mark as should_run=True by patching
        with patch.object(svc, "should_run", return_value=True):
            result = svc.run()

        mock_adapter.synthesize.assert_not_called()
        assert result.ok is True

    def test_get_sources_returns_list(self):
        """RetroService.get_sources() returns a non-empty list."""
        from bridge.services.retro import RetroService
        sources = RetroService.get_sources()
        assert isinstance(sources, list)
        assert len(sources) > 0


# ---------------------------------------------------------------------------
# #500 — CalcomWebhookHandler
# ---------------------------------------------------------------------------

class TestCalcomWebhookHandler:
    """Tests for bridge.calcom_webhook.CalcomWebhookHandler."""

    def _make_payload(self, trigger: str = "BOOKING_CREATED", uid: str = "abc123") -> bytes:
        data = {
            "triggerEvent": trigger,
            "payload": {
                "uid": uid,
                "title": "Demo Call",
                "startTime": "2026-04-20T15:00:00Z",
                "endTime": "2026-04-20T15:30:00Z",
                "attendees": [{"name": "Alex", "email": "alex@stripe.com"}],
                "organizer": {"name": "the operator", "email": "operator@bumba.io"},
            },
        }
        return json.dumps(data).encode()

    def _make_request(self, body: bytes, headers: dict | None = None):
        req = MagicMock()
        req.read = AsyncMock(return_value=body)
        req.headers = {**(headers or {})}
        req.remote = "127.0.0.1"
        return req

    def _signed_headers(self, body: bytes, secret: str = "testsecret") -> dict[str, str]:
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return {"X-Cal-Signature-256": sig}

    def _make_signed_request(self, body: bytes, secret: str = "testsecret"):
        return self._make_request(body, headers=self._signed_headers(body, secret))

    @pytest.mark.asyncio
    async def test_booking_created_publishes_event(self):
        """BOOKING_CREATED webhook publishes calcom.booking.created to event bus."""
        from bridge.calcom_webhook import CalcomWebhookHandler

        CalcomWebhookHandler.clear_dedup_cache()
        bus = MagicMock()
        handler = CalcomWebhookHandler(event_bus=bus)

        body = self._make_payload("BOOKING_CREATED", uid="uid-001")
        req = self._make_signed_request(body)

        with patch("bridge.calcom_webhook._read_secret", return_value="testsecret"):
            resp = await handler.handle(req)

        assert resp.status == 200
        bus.publish.assert_called_once()
        call_kwargs = bus.publish.call_args
        assert call_kwargs[0][0] == "calcom.booking.created"

    @pytest.mark.asyncio
    async def test_booking_cancelled_publishes_event(self):
        """BOOKING_CANCELLED webhook publishes calcom.booking.cancelled."""
        from bridge.calcom_webhook import CalcomWebhookHandler

        CalcomWebhookHandler.clear_dedup_cache()
        bus = MagicMock()
        handler = CalcomWebhookHandler(event_bus=bus)

        body = self._make_payload("BOOKING_CANCELLED", uid="uid-002")
        req = self._make_signed_request(body)

        with patch("bridge.calcom_webhook._read_secret", return_value="testsecret"):
            resp = await handler.handle(req)

        assert resp.status == 200
        call_event = bus.publish.call_args[0][0]
        assert call_event == "calcom.booking.cancelled"

    @pytest.mark.asyncio
    async def test_bad_signature_returns_401(self):
        """Bad HMAC-SHA256 signature returns 401 and does not publish."""
        from bridge.calcom_webhook import CalcomWebhookHandler

        CalcomWebhookHandler.clear_dedup_cache()
        bus = MagicMock()
        handler = CalcomWebhookHandler(event_bus=bus)

        body = self._make_payload("BOOKING_CREATED", uid="uid-003")
        req = self._make_request(body, headers={"X-Cal-Signature-256": "badhex"})

        with patch("bridge.calcom_webhook._read_secret", return_value="mysecret"):
            resp = await handler.handle(req)

        assert resp.status == 401
        bus.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_signature_accepted(self):
        """Valid HMAC-SHA256 signature is accepted."""
        from bridge.calcom_webhook import CalcomWebhookHandler

        CalcomWebhookHandler.clear_dedup_cache()
        bus = MagicMock()
        handler = CalcomWebhookHandler(event_bus=bus)

        secret = "testsecret"
        body = self._make_payload("BOOKING_CREATED", uid="uid-004")
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        req = self._make_request(body, headers={"X-Cal-Signature-256": sig})

        with patch("bridge.calcom_webhook._read_secret", return_value=secret):
            resp = await handler.handle(req)

        assert resp.status == 200
        bus.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_duplicate_skipped(self):
        """Duplicate webhook (same event_type+uid) is deduped and not re-published."""
        from bridge.calcom_webhook import CalcomWebhookHandler

        CalcomWebhookHandler.clear_dedup_cache()
        bus = MagicMock()
        handler = CalcomWebhookHandler(event_bus=bus)

        body = self._make_payload("BOOKING_CREATED", uid="uid-005")

        with patch("bridge.calcom_webhook._read_secret", return_value="testsecret"):
            await handler.handle(self._make_signed_request(body))
            resp = await handler.handle(self._make_signed_request(body))

        assert resp.status == 200
        # Published only once
        assert bus.publish.call_count == 1

    @pytest.mark.asyncio
    async def test_unknown_trigger_published_as_unknown(self):
        """Unknown triggerEvent maps to calcom.booking.unknown."""
        from bridge.calcom_webhook import CalcomWebhookHandler

        CalcomWebhookHandler.clear_dedup_cache()
        bus = MagicMock()
        handler = CalcomWebhookHandler(event_bus=bus)

        body = json.dumps({
            "triggerEvent": "BOOKING_CUSTOM_THING",
            "payload": {"uid": "uid-006"},
        }).encode()

        with patch("bridge.calcom_webhook._read_secret", return_value="testsecret"):
            resp = await handler.handle(self._make_signed_request(body))

        assert resp.status == 200
        call_event = bus.publish.call_args[0][0]
        assert call_event == "calcom.booking.unknown"

    @pytest.mark.asyncio
    async def test_invalid_json_returns_400(self):
        """Malformed JSON body returns 400."""
        from bridge.calcom_webhook import CalcomWebhookHandler

        CalcomWebhookHandler.clear_dedup_cache()
        handler = CalcomWebhookHandler(event_bus=None)
        body = b"not json"
        req = self._make_signed_request(body)

        with patch("bridge.calcom_webhook._read_secret", return_value="testsecret"):
            resp = await handler.handle(req)

        assert resp.status == 400


# ---------------------------------------------------------------------------
# #501 + #503 — MeetingPrebriefService
# ---------------------------------------------------------------------------

class TestMeetingPrebriefService:
    """Tests for bridge.services.meeting_prebrief.MeetingPrebriefService."""

    def _make_booking(
        self,
        uid: str = "b-001",
        minutes_from_now: float = 30.0,
    ) -> dict:
        from datetime import datetime, timedelta, timezone
        start = datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)
        return {
            "uid": uid,
            "title": "Product sync",
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(minutes=30)).isoformat(),
            "attendee_name": "Alex Chen",
            "attendee_email": "alex@example.com",
            "meeting_url": "https://meet.google.com/abc",
        }

    def test_check_upcoming_sends_prebrief(self, tmp_dir):
        """check_upcoming sends a prebrief for a booking at T-30min."""
        from bridge.services.meeting_prebrief import MeetingPrebriefService

        booking = self._make_booking(uid="b-100", minutes_from_now=30.0)
        mock_ci = MagicMock()
        mock_ci.get_upcoming_bookings.return_value = [booking]

        svc = MeetingPrebriefService(
            tmp_dir, "channel123", calcom_interface=mock_ci,
            enable_talking_points=False,
        )
        sent = svc.check_upcoming()
        assert sent == 1

        # A message file should exist
        msgs = list((tmp_dir / "service_messages").glob("*.json"))
        assert len(msgs) >= 1
        msg_data = json.loads(msgs[0].read_text())
        assert "Product sync" in msg_data["text"]

    def test_check_upcoming_skips_already_sent(self, tmp_dir):
        """check_upcoming does not send a second prebrief for the same uid."""
        from bridge.services.meeting_prebrief import MeetingPrebriefService

        booking = self._make_booking(uid="b-200", minutes_from_now=30.0)
        mock_ci = MagicMock()
        mock_ci.get_upcoming_bookings.return_value = [booking]

        svc = MeetingPrebriefService(tmp_dir, "channel123", calcom_interface=mock_ci, enable_talking_points=False)
        svc.check_upcoming()
        sent2 = svc.check_upcoming()  # second scan
        assert sent2 == 0

    def test_check_upcoming_skips_out_of_window(self, tmp_dir):
        """check_upcoming skips a booking that is 60 min away (outside ±5min of T-30)."""
        from bridge.services.meeting_prebrief import MeetingPrebriefService

        booking = self._make_booking(uid="b-300", minutes_from_now=60.0)
        mock_ci = MagicMock()
        mock_ci.get_upcoming_bookings.return_value = [booking]

        svc = MeetingPrebriefService(tmp_dir, "channel123", calcom_interface=mock_ci, enable_talking_points=False)
        sent = svc.check_upcoming()
        assert sent == 0

    def test_backfill_sends_late_prebrief(self, tmp_dir):
        """backfill_missed sends a late prebrief for a meeting that started 1h ago."""
        from bridge.services.meeting_prebrief import MeetingPrebriefService
        from datetime import datetime, timedelta, timezone

        start = datetime.now(timezone.utc) - timedelta(hours=1)
        booking = {
            "uid": "b-400",
            "title": "Missed call",
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(minutes=30)).isoformat(),
            "attendee_name": "Bob",
            "attendee_email": "bob@example.com",
        }
        mock_ci = MagicMock()
        mock_ci.get_upcoming_bookings.return_value = [booking]

        svc = MeetingPrebriefService(tmp_dir, "channel123", calcom_interface=mock_ci, enable_talking_points=False)
        backfilled = svc.backfill_missed()
        assert backfilled == 1

        msgs = list((tmp_dir / "service_messages").glob("*.json"))
        assert any("Late prebrief" in json.loads(m.read_text())["text"] for m in msgs)

    def test_backfill_skips_already_sent(self, tmp_dir):
        """backfill_missed does not re-send if already marked sent."""
        from bridge.services.meeting_prebrief import MeetingPrebriefService
        from datetime import datetime, timedelta, timezone

        start = datetime.now(timezone.utc) - timedelta(hours=1)
        booking = {
            "uid": "b-500",
            "title": "Already done",
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(minutes=30)).isoformat(),
        }
        mock_ci = MagicMock()
        mock_ci.get_upcoming_bookings.return_value = [booking]

        svc = MeetingPrebriefService(tmp_dir, "channel123", calcom_interface=mock_ci, enable_talking_points=False)
        svc._mark_sent("b-500")  # simulate prior send
        backfilled = svc.backfill_missed()
        assert backfilled == 0

    def test_run_returns_service_result(self, tmp_dir):
        """run() returns a ServiceResult with correct service name."""
        from bridge.services.meeting_prebrief import MeetingPrebriefService
        from bridge.services.result import ServiceResult

        mock_ci = MagicMock()
        mock_ci.get_upcoming_bookings.return_value = []

        svc = MeetingPrebriefService(tmp_dir, "channel123", calcom_interface=mock_ci, enable_talking_points=False)
        result = svc.run()

        assert isinstance(result, ServiceResult)
        assert result.service == "meeting_prebrief"
        assert result.ok is True

    def test_card_composed_without_research(self, tmp_dir):
        """Card is posted even when research returns None."""
        from bridge.services.meeting_prebrief import _compose_card

        booking = self._make_booking()
        card = _compose_card(booking, late=False, email_snippet=None, company_info=None, talking_points=None)

        assert "Product sync" in card
        assert "Alex Chen" in card

    def test_card_includes_late_marker(self, tmp_dir):
        """Late prebrief card includes 'Late prebrief' header."""
        from bridge.services.meeting_prebrief import _compose_card

        booking = self._make_booking()
        card = _compose_card(booking, late=True)
        assert "Late prebrief" in card


# ---------------------------------------------------------------------------
# #502 — ServiceBase narration helpers
# ---------------------------------------------------------------------------

class TestServiceBaseNarration:
    """Tests for narrate_start and narrate_complete in ServiceBase."""

    def test_narrate_start_writes_message_file(self, tmp_dir):
        """narrate_start writes a service_narration message file."""
        from bridge.services.base import ServiceBase

        svc = ServiceBase(tmp_dir)
        svc.narrate_start("channel123", "Scanning inbox for new mail.")

        msgs = list((tmp_dir / "service_messages").glob("service_narration_*.json"))
        assert len(msgs) == 1
        data = json.loads(msgs[0].read_text())
        assert data["text"] == "Scanning inbox for new mail."
        assert data["source"] == "service_narration"

    def test_narrate_complete_uses_result_narration(self, tmp_dir):
        """narrate_complete uses ServiceResult.narration when set."""
        from bridge.services.base import ServiceBase
        from bridge.services.result import ServiceResult

        svc = ServiceBase(tmp_dir)
        result = ServiceResult(
            service="email",
            ok=True,
            work_items=3,
            duration_ms=500,
            cost_usd=0.0,
            narration="Processed 3 new emails, flagged 1 for reply.",
        )
        svc.narrate_complete("channel123", "Email", result)

        msgs = list((tmp_dir / "service_messages").glob("service_narration_*.json"))
        assert len(msgs) == 1
        data = json.loads(msgs[0].read_text())
        assert "Processed 3 new emails" in data["text"]

    def test_narrate_complete_fallback_to_completion_line(self, tmp_dir):
        """narrate_complete falls back to completion line when narration is None."""
        from bridge.services.base import ServiceBase
        from bridge.services.result import ServiceResult

        svc = ServiceBase(tmp_dir)
        result = ServiceResult(
            service="email",
            ok=True,
            work_items=5,
            duration_ms=200,
            cost_usd=0.0,
            narration=None,
        )
        svc.narrate_complete("channel123", "Email", result)

        msgs = list((tmp_dir / "service_messages").glob("service_narration_*.json"))
        assert len(msgs) == 1
        data = json.loads(msgs[0].read_text())
        # completion line format: [SERVICE][OK email ...]
        assert "[SERVICE]" in data["text"] or "email" in data["text"].lower()

    def test_narrate_start_does_not_raise_on_error(self, tmp_dir):
        """narrate_start swallows exceptions — never crashes the service."""
        from bridge.services.base import ServiceBase

        svc = ServiceBase(tmp_dir)
        # Make messages_dir unwriteable by pointing to a file
        svc.messages_dir = tmp_dir / "not_a_dir.txt"
        (tmp_dir / "not_a_dir.txt").write_text("")
        # Sanity: the original messages_dir (created by ServiceBase.__init__)
        # is empty; if the swallow path is broken and writes go through
        # to the original dir, we'd see narration files appear here.
        original_dir = tmp_dir / "service_messages"
        assert list(original_dir.glob("*.json")) == []

        # Should not raise
        svc.narrate_start("channel123", "Starting scan.")
        # No narration message was written (the write target was a file,
        # so deliver_message raised internally and the helper swallowed it).
        assert list(original_dir.glob("service_narration_*.json")) == []

    def test_narrate_complete_does_not_raise_on_error(self, tmp_dir):
        """narrate_complete swallows exceptions — never crashes the service."""
        from bridge.services.base import ServiceBase

        svc = ServiceBase(tmp_dir)
        svc.messages_dir = tmp_dir / "not_a_dir.txt"
        (tmp_dir / "not_a_dir.txt").write_text("")
        original_dir = tmp_dir / "service_messages"
        assert list(original_dir.glob("*.json")) == []

        bad_result = MagicMock()
        bad_result.narration = None
        # Should not raise
        svc.narrate_complete("channel123", "Email", bad_result)
        # No narration message was written.
        assert list(original_dir.glob("service_narration_*.json")) == []
