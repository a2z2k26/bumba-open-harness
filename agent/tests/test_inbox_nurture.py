"""Tests for InboxNurtureService (Z2-S5.2)."""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.services.inbox_nurture import (
    InboxNurtureService,
    _is_autoresponder,
    _score_thread,
    _build_draft_prompt,
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
    return InboxNurtureService(data_dir=tmp_dir, chat_id="test-chat")


# ---------------------------------------------------------------------------
# _is_autoresponder
# ---------------------------------------------------------------------------

class TestIsAutoresponder:
    def test_noreply_domain(self):
        assert _is_autoresponder("noreply@example.com") is True

    def test_no_reply_hyphen(self):
        assert _is_autoresponder("no-reply@service.io") is True

    def test_donotreply(self):
        assert _is_autoresponder("donotreply@bank.com") is True

    def test_normal_sender(self):
        assert _is_autoresponder("alice@example.com") is False

    def test_support_at_normal(self):
        assert _is_autoresponder("support@mycompany.com") is False


# ---------------------------------------------------------------------------
# _score_thread
# ---------------------------------------------------------------------------

class TestScoreThread:
    def test_staleness_contributes_to_score(self):
        t = {"age_hours": 96.0, "subject": "", "snippet": ""}
        assert _score_thread(t) == pytest.approx(96.0)

    def test_cta_keyword_adds_bonus(self):
        t = {"age_hours": 48.0, "subject": "Please review this", "snippet": ""}
        score = _score_thread(t)
        # "please" and "review" are both CTA keywords → +10
        assert score > 48.0

    def test_staleness_capped_at_240h(self):
        t = {"age_hours": 1000.0, "subject": "", "snippet": ""}
        assert _score_thread(t) == pytest.approx(240.0)

    def test_older_thread_scores_higher(self):
        old = {"age_hours": 120.0, "subject": "", "snippet": ""}
        new = {"age_hours": 50.0, "subject": "", "snippet": ""}
        assert _score_thread(old) > _score_thread(new)


# ---------------------------------------------------------------------------
# _build_draft_prompt
# ---------------------------------------------------------------------------

class TestBuildDraftPrompt:
    def test_contains_subject(self):
        t = {"subject": "Q4 budget review", "from_addr": "boss@corp.com",
             "snippet": "please get back to me", "age_hours": 72.0}
        prompt = _build_draft_prompt(t)
        assert "Q4 budget review" in prompt

    def test_contains_sender(self):
        t = {"subject": "Hi", "from_addr": "alice@example.com",
             "snippet": "", "age_hours": 50.0}
        prompt = _build_draft_prompt(t)
        assert "alice@example.com" in prompt


# ---------------------------------------------------------------------------
# InboxNurtureService.should_run
# ---------------------------------------------------------------------------

class TestShouldRun:
    def test_runs_when_no_prior_run(self, svc):
        assert svc.should_run() is True

    def test_skips_when_already_ran_today(self, svc):
        state = svc.load_state("inbox-nurture-state.json")
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        svc.save_state(state, "inbox-nurture-state.json")
        assert svc.should_run() is False

    def test_runs_when_last_run_yesterday(self, svc):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        state = svc.load_state("inbox-nurture-state.json")
        state["last_run"] = yesterday
        svc.save_state(state, "inbox-nurture-state.json")
        assert svc.should_run() is True


# ---------------------------------------------------------------------------
# InboxNurtureService.run — inbox_zero path
# ---------------------------------------------------------------------------

class TestRunInboxZero:
    def test_inbox_zero_skips(self, svc):
        with patch.object(svc, "_fetch_stale_threads", return_value=[]):
            result = svc.run()
        assert result.ok is True
        assert result.skip_reason == "inbox_zero"
        assert result.work_items == 0

    def test_inbox_zero_delivers_message(self, svc):
        with patch.object(svc, "_fetch_stale_threads", return_value=[]):
            svc.run()
        msgs_dir = Path(svc.data_dir) / "service_messages"
        files = list(msgs_dir.glob("*.json"))
        assert len(files) >= 1


# ---------------------------------------------------------------------------
# InboxNurtureService.run — happy path (one stale thread)
# ---------------------------------------------------------------------------

class TestRunHappyPath:
    def _fake_thread(self):
        return {
            "id": "msg001",
            "from_addr": "client@acme.com",
            "subject": "Follow up on proposal",
            "snippet": "Please review and let me know",
            "age_hours": 72.0,
        }

    def test_drafts_one_reply(self, svc):
        thread = self._fake_thread()
        with (
            patch.object(svc, "_fetch_stale_threads", return_value=[thread]),
            patch.object(svc, "generate_draft", return_value="Hi, thanks for reaching out..."),
        ):
            result = svc.run()
        assert result.ok is True
        assert result.work_items == 1
        assert result.skip_reason is None

    def test_hitl_message_written(self, svc):
        thread = self._fake_thread()
        with (
            patch.object(svc, "_fetch_stale_threads", return_value=[thread]),
            patch.object(svc, "generate_draft", return_value="Draft body here"),
        ):
            svc.run()
        msgs_dir = Path(svc.data_dir) / "service_messages"
        files = list(msgs_dir.glob("*.json"))
        assert any("inbox" in f.name for f in files) or len(files) >= 1

    def test_pending_draft_json_written(self, svc):
        thread = self._fake_thread()
        with (
            patch.object(svc, "_fetch_stale_threads", return_value=[thread]),
            patch.object(svc, "generate_draft", return_value="Draft body"),
        ):
            svc.run()
        pending = Path(svc.data_dir) / "inbox_nurture_pending.json"
        assert pending.exists()
        data = json.loads(pending.read_text())
        assert data["thread_id"] == "msg001"
        assert data["draft"] == "Draft body"

    def test_state_recorded_as_success(self, svc):
        thread = self._fake_thread()
        with (
            patch.object(svc, "_fetch_stale_threads", return_value=[thread]),
            patch.object(svc, "generate_draft", return_value="Draft"),
        ):
            svc.run()
        state = svc.load_state("inbox-nurture-state.json")
        assert state["last_run"] is not None
        assert state["consecutive_failures"] == 0

    def test_picks_highest_scoring_thread(self, svc):
        """When multiple threads exist, the highest-scored one is drafted."""
        old_thread = {
            "id": "old", "from_addr": "a@b.com",
            "subject": "Old thread", "snippet": "", "age_hours": 200.0,
        }
        new_thread = {
            "id": "new", "from_addr": "c@d.com",
            "subject": "New thread", "snippet": "", "age_hours": 50.0,
        }
        drafted = []

        def capture_draft(thread):
            drafted.append(thread["id"])
            return "Draft"

        with (
            patch.object(svc, "_fetch_stale_threads", return_value=[old_thread, new_thread]),
            patch.object(svc, "generate_draft", side_effect=capture_draft),
        ):
            svc.run()

        assert drafted == ["old"]


# ---------------------------------------------------------------------------
# InboxNurtureService.run — already ran today
# ---------------------------------------------------------------------------

class TestRunAlreadyRanToday:
    def test_skip_result(self, svc):
        state = svc.load_state("inbox-nurture-state.json")
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        svc.save_state(state, "inbox-nurture-state.json")
        result = svc.run()
        assert result.skip_reason == "already_ran_today"
        assert result.work_items == 0


# ---------------------------------------------------------------------------
# InboxNurtureService.run — generate_draft fallback
# ---------------------------------------------------------------------------

class TestDraftFallback:
    def test_fallback_draft_on_claude_failure(self, svc):
        thread = {
            "id": "t1", "from_addr": "x@y.com",
            "subject": "Test", "snippet": "", "age_hours": 60.0,
        }
        # generate_draft should return fallback text when subprocess fails
        with (
            patch("subprocess.run", side_effect=FileNotFoundError("no claude")),
            patch.object(svc, "_fetch_stale_threads", return_value=[thread]),
        ):
            result = svc.run()
        assert result.ok is True
        pending = Path(svc.data_dir) / "inbox_nurture_pending.json"
        assert pending.exists()
        data = json.loads(pending.read_text())
        # Fallback draft contains some text
        assert len(data["draft"]) > 10
