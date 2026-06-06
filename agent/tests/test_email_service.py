"""Tests for bridge.services.email."""

from __future__ import annotations

import time
from datetime import datetime
from unittest.mock import patch

import pytest

from bridge.services.email import EmailService, CATEGORY_URGENT, CATEGORY_ACTIONABLE, CATEGORY_INFO


@pytest.fixture
def email_service(tmp_path):
    """Create an EmailService with test paths."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    return EmailService(
        data_dir=data_dir,
        chat_id="test-chat-123",
        active_hours_start=0,
        active_hours_end=24,
        digest_interval=0,  # Always allow
    )


class TestEmailShouldRun:
    """Timing and dedup guards."""

    def test_should_run_within_window(self, email_service):
        assert email_service.should_run() is True

    def test_should_run_respects_interval(self, email_service):
        email_service.digest_interval = 7200
        state = {"last_check_time": time.time()}
        email_service.save_state(state, filename="email-state.json")
        assert email_service.should_run() is False

    def test_should_run_after_interval(self, email_service):
        email_service.digest_interval = 7200
        state = {"last_check_time": time.time() - 8000}
        email_service.save_state(state, filename="email-state.json")
        assert email_service.should_run() is True

    def test_should_run_outside_hours(self, tmp_path):
        data_dir = tmp_path / "data2"
        data_dir.mkdir()
        svc = EmailService(
            data_dir=data_dir,
            chat_id="test",
            active_hours_start=3,
            active_hours_end=4,
        )
        # Outside 3-4am window most of the time
        now = datetime.now()
        if 3 <= now.hour < 4:
            pytest.skip("Test depends on being outside 3-4am window")
        assert svc.should_run() is False


class TestEmailCategorization:
    """Email categorization logic."""

    def test_starred_is_urgent(self, email_service):
        msg = {"labels": ["STARRED"], "subject": "Hello"}
        assert email_service._categorize(msg) == CATEGORY_URGENT

    def test_important_is_urgent(self, email_service):
        msg = {"labels": ["IMPORTANT"], "subject": "Hello"}
        assert email_service._categorize(msg) == CATEGORY_URGENT

    def test_urgent_subject_is_urgent(self, email_service):
        msg = {"labels": [], "subject": "URGENT: server down"}
        assert email_service._categorize(msg) == CATEGORY_URGENT

    def test_review_is_actionable(self, email_service):
        msg = {"labels": [], "subject": "Please review this PR"}
        assert email_service._categorize(msg) == CATEGORY_ACTIONABLE

    def test_normal_is_info(self, email_service):
        msg = {"labels": [], "subject": "Weekly newsletter"}
        assert email_service._categorize(msg) == CATEGORY_INFO


class TestEmailDigest:
    """Digest compilation."""

    @patch("bridge.services.email.EmailService.ACCOUNTS", ["agent"])
    def test_compile_with_messages(self, email_service):
        mock_messages = [
            {"id": "1", "from_addr": "alice@test.com", "subject": "Hello", "labels": [], "snippet": "Hi"},
        ]
        with patch("bridge.services.gmail_interface.get_unread_count", return_value=1), \
             patch("bridge.services.gmail_interface.get_unread_messages", return_value=mock_messages):
            result = email_service.compile()
            assert result is not None
            assert "alice@test.com" in result
            assert "Hello" in result
            assert "1 unread" in result

    @patch("bridge.services.email.EmailService.ACCOUNTS", ["agent"])
    def test_compile_empty_inbox(self, email_service):
        with patch("bridge.services.gmail_interface.get_unread_count", return_value=0):
            result = email_service.compile()
            assert result is None

    @patch("bridge.services.email.EmailService.ACCOUNTS", ["agent"])
    def test_compile_dedup_same_count(self, email_service):
        state = {"last_digest_count": 3, "last_check_time": 0}
        email_service.save_state(state, filename="email-state.json")
        with patch("bridge.services.gmail_interface.get_unread_count", return_value=3), \
             patch("bridge.services.gmail_interface.get_unread_messages", return_value=[]):
            result = email_service.compile()
            assert result is None

    @patch("bridge.services.email.EmailService.ACCOUNTS", ["agent"])
    def test_run_sends_message(self, email_service):
        mock_messages = [
            {"id": "1", "from_addr": "bob@test.com", "subject": "Test", "labels": [], "snippet": "Hi"},
        ]
        with patch("bridge.services.gmail_interface.get_unread_count", return_value=1), \
             patch("bridge.services.gmail_interface.get_unread_messages", return_value=mock_messages):
            result = email_service.run()
            assert result.ok is True
            msgs = list(email_service.messages_dir.glob("email-digest_*.json"))
            assert len(msgs) == 1

    @patch("bridge.services.email.EmailService.ACCOUNTS", ["agent"])
    def test_state_updated_after_run(self, email_service):
        with patch("bridge.services.gmail_interface.get_unread_count", return_value=0):
            email_service.run()
            state = email_service.load_state(filename="email-state.json")
            assert "last_check_time" in state
