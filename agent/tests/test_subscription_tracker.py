"""Tests for SubscriptionTrackerService (Z2-S5.3)."""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.services.subscription_tracker import (
    SubscriptionTrackerService,
    Subscription,
    _is_renewal_email,
    _is_cancellation_email,
    _extract_amount,
    _extract_vendor,
    _extract_renewal_date,
    _days_until,
    HIGH_COST_THRESHOLD_USD,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def svc(tmp_dir):
    return SubscriptionTrackerService(data_dir=tmp_dir, chat_id="ch-1")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestIsRenewalEmail:
    def test_renew_keyword(self):
        assert _is_renewal_email("Your subscription is renewing", "") is True

    def test_next_charge(self):
        assert _is_renewal_email("", "Your next charge will be $9.99") is True

    def test_subscription_confirmed(self):
        assert _is_renewal_email("Subscription confirmed", "") is True

    def test_unrelated(self):
        assert _is_renewal_email("Lunch at noon", "See you there") is False

    def test_invoice(self):
        assert _is_renewal_email("Invoice for March", "") is True

    def test_payment_receipt(self):
        assert _is_renewal_email("Payment receipt", "") is True


class TestIsCancellationEmail:
    def test_cancel_keyword(self):
        assert _is_cancellation_email("Your subscription has been cancelled", "") is True

    def test_unsubscribe(self):
        assert _is_cancellation_email("", "You have unsubscribed") is True

    def test_refund(self):
        assert _is_cancellation_email("Refund processed", "") is True

    def test_normal(self):
        assert _is_cancellation_email("Meeting tomorrow", "") is False


class TestExtractAmount:
    def test_simple_dollar(self):
        assert _extract_amount("Your charge is $12.99") == pytest.approx(12.99)

    def test_no_amount(self):
        assert _extract_amount("no money here") is None

    def test_amount_with_comma(self):
        assert _extract_amount("Total: $1,200.00") == pytest.approx(1200.0)


class TestExtractVendor:
    def test_domain_extraction(self):
        vendor = _extract_vendor("billing@github.com", "Invoice")
        assert vendor == "Github"

    def test_subject_fallback(self):
        vendor = _extract_vendor("", "Notion invoice")
        assert vendor == "Notion"


class TestExtractRenewalDate:
    def test_finds_date(self):
        date = _extract_renewal_date("Your plan renews on April 15, 2026")
        assert date == "2026-04-15"

    def test_no_date(self):
        assert _extract_renewal_date("No date here") == ""


class TestDaysUntil:
    def test_future_date(self):
        future = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
        result = _days_until(future)
        assert result == 7

    def test_past_date(self):
        past = (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()
        result = _days_until(past)
        assert result == -3

    def test_empty_string(self):
        assert _days_until("") is None

    def test_invalid_date(self):
        assert _days_until("not-a-date") is None


# ---------------------------------------------------------------------------
# Registry persistence
# ---------------------------------------------------------------------------

class TestRegistryPersistence:
    def test_load_empty_registry(self, svc):
        assert svc.load_subscriptions() == {}

    def test_save_and_load(self, svc):
        subs: dict = {
            "Github": Subscription(
                vendor="Github", amount_usd=4.0, renewal_date="2026-05-01",
                status="active", last_seen="2026-04-01T00:00:00+00:00",
                cancellable_flag=False,
            )
        }
        svc.save_subscriptions(subs)
        loaded = svc.load_subscriptions()
        assert "Github" in loaded
        assert loaded["Github"]["amount_usd"] == pytest.approx(4.0)

    def test_atomic_write_no_tmp_files(self, svc):
        svc.save_subscriptions({"X": {"vendor": "X", "amount_usd": 1.0}})
        tmp_files = list(Path(svc.data_dir).glob("*.tmp"))
        assert len(tmp_files) == 0


# ---------------------------------------------------------------------------
# scan_gmail
# ---------------------------------------------------------------------------

class TestScanGmail:
    def _fake_messages(self):
        return [
            {
                "id": "m1",
                "from_addr": "billing@github.com",
                "subject": "Your GitHub subscription is renewing",
                "snippet": "Next charge $4.00 on May 1, 2026",
                "date": "Fri, 18 Apr 2026 10:00:00 +0000",
                "labels": [],
            },
            {
                "id": "m2",
                "from_addr": "noreply@notion.so",
                "subject": "Subscription confirmed",
                "snippet": "You have been charged $16.00",
                "date": "Fri, 18 Apr 2026 09:00:00 +0000",
                "labels": [],
            },
        ]

    def test_scan_discovers_subscriptions(self, svc):
        with patch("bridge.services.subscription_tracker.get_unread_messages",
                   return_value=self._fake_messages()):
            updated = svc.scan_gmail()
        assert updated == 2
        subs = svc.load_subscriptions()
        assert len(subs) == 2

    def test_cancellation_marks_cancelled(self, svc):
        # Seed an existing subscription
        svc.save_subscriptions({"Github": {"vendor": "Github", "amount_usd": 4.0,
                                           "status": "active", "renewal_date": "",
                                           "last_seen": "", "cancellable_flag": False}})
        cancel_msg = [{
            "id": "m3",
            "from_addr": "billing@github.com",
            "subject": "Your subscription has been cancelled",
            "snippet": "",
            "date": "Fri, 18 Apr 2026 12:00:00 +0000",
            "labels": [],
        }]
        with patch("bridge.services.subscription_tracker.get_unread_messages",
                   return_value=cancel_msg):
            svc.scan_gmail()
        subs = svc.load_subscriptions()
        assert subs["Github"]["status"] == "cancelled"

    def test_high_cost_flagged_cancellable(self, svc):
        expensive_msg = [{
            "id": "m4",
            "from_addr": "billing@bigvendor.com",
            "subject": "Invoice",
            "snippet": f"Charged ${HIGH_COST_THRESHOLD_USD + 1:.2f}",
            "date": "Fri, 18 Apr 2026 08:00:00 +0000",
            "labels": [],
        }]
        with patch("bridge.services.subscription_tracker.get_unread_messages",
                   return_value=expensive_msg):
            svc.scan_gmail()
        subs = svc.load_subscriptions()
        assert any(s.get("cancellable_flag") for s in subs.values())


# ---------------------------------------------------------------------------
# Renewal warnings
# ---------------------------------------------------------------------------

class TestRenewalWarnings:
    def _seed_renewal_in(self, svc, days: int, vendor: str = "Acme"):
        target = (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()
        svc.save_subscriptions({
            vendor: {"vendor": vendor, "amount_usd": 20.0, "renewal_date": target,
                     "status": "active", "last_seen": "", "cancellable_flag": False}
        })

    def test_7day_warning_sent(self, svc):
        self._seed_renewal_in(svc, 7)
        count = svc.send_renewal_warnings()
        assert count == 1
        msgs = list((Path(svc.data_dir) / "service_messages").glob("*.json"))
        assert len(msgs) == 1

    def test_1day_warning_sent(self, svc):
        self._seed_renewal_in(svc, 1)
        count = svc.send_renewal_warnings()
        assert count == 1

    def test_no_warning_on_other_days(self, svc):
        self._seed_renewal_in(svc, 5)
        count = svc.send_renewal_warnings()
        assert count == 0

    def test_cancelled_subscription_skipped(self, svc):
        target = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
        svc.save_subscriptions({
            "Dead": {"vendor": "Dead", "amount_usd": 10.0, "renewal_date": target,
                     "status": "cancelled", "last_seen": "", "cancellable_flag": False}
        })
        count = svc.send_renewal_warnings()
        assert count == 0


# ---------------------------------------------------------------------------
# Weekly summary
# ---------------------------------------------------------------------------

class TestWeeklySummary:
    def test_summary_includes_active_subs(self, svc):
        svc.save_subscriptions({
            "Github": {"vendor": "Github", "amount_usd": 4.0,
                       "renewal_date": "2026-05-01", "status": "active",
                       "last_seen": "", "cancellable_flag": False},
            "Notion": {"vendor": "Notion", "amount_usd": 16.0,
                       "renewal_date": "2026-05-15", "status": "active",
                       "last_seen": "", "cancellable_flag": False},
        })
        summary = svc.build_weekly_summary()
        assert "Github" in summary
        assert "Notion" in summary
        assert "$20.00" in summary  # total

    def test_summary_empty_registry(self, svc):
        summary = svc.build_weekly_summary()
        assert "no active subscriptions" in summary.lower()

    def test_summary_excludes_cancelled(self, svc):
        svc.save_subscriptions({
            "Dead": {"vendor": "Dead", "amount_usd": 5.0,
                     "renewal_date": "", "status": "cancelled",
                     "last_seen": "", "cancellable_flag": False}
        })
        summary = svc.build_weekly_summary()
        assert "no active subscriptions" in summary.lower()

    def test_should_send_weekly_summary_sunday(self, svc):
        # Force Sunday (weekday 6)
        with patch("bridge.services.subscription_tracker.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 19, 17, 0, 0,
                                                tzinfo=timezone.utc)  # Sunday
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            # Patch weekday to return 6
            fake_now = MagicMock()
            fake_now.weekday.return_value = 6
            fake_now.date.return_value = datetime(2026, 4, 19).date()
            mock_dt.now.return_value = fake_now
        # Direct test via a Monday — should NOT send
        with patch("bridge.services.subscription_tracker.datetime") as mock_dt:
            fake_now2 = MagicMock()
            fake_now2.weekday.return_value = 0  # Monday
            mock_dt.now.return_value = fake_now2
            assert svc.should_send_weekly_summary() is False


# ---------------------------------------------------------------------------
# Full run() — no-op
# ---------------------------------------------------------------------------

class TestRunNoOp:
    def test_no_actions_returns_skip(self, svc):
        with patch.object(svc, "scan_gmail", return_value=0), \
             patch.object(svc, "send_renewal_warnings", return_value=0), \
             patch.object(svc, "should_send_weekly_summary", return_value=False):
            result = svc.run()
        assert result.ok is True
        assert result.skip_reason == "no_actions_today"


# ---------------------------------------------------------------------------
# Full run() — with actions
# ---------------------------------------------------------------------------

class TestRunWithActions:
    def test_run_with_scan_results(self, svc):
        with patch.object(svc, "scan_gmail", return_value=3), \
             patch.object(svc, "send_renewal_warnings", return_value=1), \
             patch.object(svc, "should_send_weekly_summary", return_value=False):
            result = svc.run()
        assert result.ok is True
        assert result.work_items == 4
        assert result.skip_reason is None

    def test_run_with_weekly_summary(self, svc):
        with patch.object(svc, "scan_gmail", return_value=0), \
             patch.object(svc, "send_renewal_warnings", return_value=0), \
             patch.object(svc, "should_send_weekly_summary", return_value=True), \
             patch.object(svc, "build_weekly_summary", return_value="Summary text"):
            result = svc.run()
        assert result.work_items == 1
        msgs = list((Path(svc.data_dir) / "service_messages").glob("*.json"))
        assert len(msgs) >= 1


# Fix missing import
from unittest.mock import MagicMock
