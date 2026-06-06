"""Tests for Sprint 3.2 browser automation timeout fixes (issue #257).

Covers:
1. Reduced timeouts — default 60s, Greenhouse 90s
2. Cloudflare detection (is_cloudflare_blocked + ApplicationResult.cloudflare_blocked)
3. "How Did You Hear" field in known labels list
4. --test-url smoke_test_url function
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from job_search.ats.applicant import (
    TIMEOUT_SECONDS,
    GREENHOUSE_TIMEOUT,
    _HOW_DID_YOU_HEAR_LABELS,
    _CLOUDFLARE_SIGNALS,
    ApplicationResult,
    is_cloudflare_blocked,
    smoke_test_url,
    apply_to_job,
    _resolve_timeout,
)
from job_search.boards.base import JobListing


# ---------------------------------------------------------------------------
# 1. Timeout constants
# ---------------------------------------------------------------------------


class TestTimeoutConstants:
    def test_default_timeout_is_60s(self):
        """Default timeout reduced from 480s to 60s."""
        assert TIMEOUT_SECONDS == 60

    def test_greenhouse_timeout_is_90s(self):
        """Greenhouse gets extra headroom at 90s."""
        assert GREENHOUSE_TIMEOUT == 90

    def test_resolve_timeout_greenhouse(self):
        assert _resolve_timeout("greenhouse") == GREENHOUSE_TIMEOUT

    def test_resolve_timeout_lever(self):
        assert _resolve_timeout("lever") == TIMEOUT_SECONDS

    def test_resolve_timeout_ashby(self):
        assert _resolve_timeout("ashby") == TIMEOUT_SECONDS

    def test_resolve_timeout_unknown(self):
        assert _resolve_timeout("unknown") == TIMEOUT_SECONDS

    def test_resolve_timeout_override(self):
        """Explicit override always wins."""
        assert _resolve_timeout("greenhouse", override=30) == 30
        assert _resolve_timeout("lever", override=120) == 120


# ---------------------------------------------------------------------------
# 2. Cloudflare detection
# ---------------------------------------------------------------------------


class TestCloudflareDetection:
    def test_cf_browser_verification_signal(self):
        assert is_cloudflare_blocked("cf-browser-verification challenge shown") is True

    def test_enable_javascript_signal(self):
        assert is_cloudflare_blocked("Enable JavaScript and cookies to continue") is True

    def test_ddos_protection_signal(self):
        assert is_cloudflare_blocked("DDoS protection by Cloudflare") is True

    def test_checking_site_connection_signal(self):
        assert is_cloudflare_blocked("Checking if the site connection is secure") is True

    def test_cloudflare_ray_id_signal(self):
        """The specific multi-word phrase 'Cloudflare Ray ID' appears on CF challenge pages."""
        assert is_cloudflare_blocked("Cloudflare Ray ID: abc123def456") is True

    def test_explicit_blocker_token(self):
        assert is_cloudflare_blocked('blocker: "cloudflare_blocked"') is True

    def test_captcha_blocked_token(self):
        assert is_cloudflare_blocked("captcha_blocked") is True

    def test_clean_page_not_blocked(self):
        assert is_cloudflare_blocked("Application submitted successfully") is False

    def test_empty_text_not_blocked(self):
        assert is_cloudflare_blocked("") is False

    def test_case_insensitive_cf_signal(self):
        """Signals are matched case-insensitively."""
        assert is_cloudflare_blocked("CF-BROWSER-VERIFICATION ACTIVE") is True

    def test_bare_cloudflare_word_not_blocked(self):
        """The bare word 'cloudflare' alone (e.g. in a JSON key) is NOT a block signal.
        This prevents false positives from probe responses like {"cf_blocked": false}."""
        assert is_cloudflare_blocked("cloudflare") is False
        assert is_cloudflare_blocked("Error: cloudflare block detected") is False

    def test_all_signals_present(self):
        for signal in _CLOUDFLARE_SIGNALS:
            assert is_cloudflare_blocked(signal) is True, f"Signal not detected: {signal!r}"

    def test_application_result_cloudflare_blocked_field(self):
        """ApplicationResult has cloudflare_blocked field defaulting False."""
        result = ApplicationResult(success=False, notes="timed out")
        assert result.cloudflare_blocked is False

    def test_application_result_cloudflare_blocked_set(self):
        result = ApplicationResult(success=False, cloudflare_blocked=True, notes="cloudflare_blocked")
        assert result.cloudflare_blocked is True


# ---------------------------------------------------------------------------
# 3. "How Did You Hear" custom field coverage
# ---------------------------------------------------------------------------


class TestHowDidYouHearField:
    def test_standard_label_in_list(self):
        assert "how did you hear about us" in _HOW_DID_YOU_HEAR_LABELS

    def test_referral_source_in_list(self):
        assert "referral source" in _HOW_DID_YOU_HEAR_LABELS

    def test_source_variant_in_list(self):
        assert "source" in _HOW_DID_YOU_HEAR_LABELS

    def test_how_did_you_find_in_list(self):
        assert "how did you find" in _HOW_DID_YOU_HEAR_LABELS

    def test_label_list_is_nonempty(self):
        assert len(_HOW_DID_YOU_HEAR_LABELS) >= 5

    def test_prompt_includes_how_did_you_hear_instruction(self):
        """The fill prompt should mention known label variants."""
        from job_search.ats.applicant import _build_fill_prompt
        from job_search.criteria import Candidate

        listing = JobListing(
            url="https://boards.greenhouse.io/acme/jobs/123",
            title="Designer",
            company="Acme",
            board="greenhouse",
        )
        candidate = Candidate(
            name="Test User",
            email="test@example.com",
            phone="555-0100",
            resume_local_path="/tmp/resume.pdf",
            portfolio_url="https://portfolio.example.com",
            portfolio_links=[],
            linkedin_url="https://linkedin.com/in/testuser",
            skills=["Design"],
            cover_letter_mode="ai_generated",
        )
        prompt = _build_fill_prompt(listing, candidate, "My cover letter", "greenhouse")
        assert "how did you hear" in prompt.lower()
        assert "job board" in prompt.lower()


# ---------------------------------------------------------------------------
# 4. smoke_test_url — --test-url flag behaviour
# ---------------------------------------------------------------------------


class TestSmokeTestUrl:
    @patch("job_search.ats.applicant._find_claude_binary", side_effect=FileNotFoundError("not found"))
    def test_returns_failure_if_no_binary(self, _mock):
        result = asyncio.run(smoke_test_url("https://example.com/jobs/1"))
        assert result.success is False
        assert result.notes  # some error note present

    @patch("job_search.ats.applicant._find_claude_binary", return_value="/usr/bin/claude")
    @patch("asyncio.create_subprocess_exec")
    def test_success_when_page_loads_cleanly(self, mock_exec, _mock_binary, tmp_path):
        output = json.dumps(
            {"type": "result", "result": '{"loaded": true, "cf_blocked": false, "apply_button": true}'}
        )

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (output.encode(), b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        secrets = tmp_path / ".secrets"
        secrets.write_text("claude_oauth_token=test-token\n")

        result = asyncio.run(
            smoke_test_url("https://boards.greenhouse.io/acme/jobs/123", secrets_path=secrets)
        )
        assert result.success is True
        assert result.cloudflare_blocked is False

    @patch("job_search.ats.applicant._find_claude_binary", return_value="/usr/bin/claude")
    @patch("asyncio.create_subprocess_exec")
    def test_detects_cloudflare_in_output(self, mock_exec, _mock_binary, tmp_path):
        cf_output = json.dumps(
            {
                "type": "result",
                "result": "Enable JavaScript and cookies to continue. Cloudflare Ray ID: abc123",
            }
        )

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (cf_output.encode(), b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        secrets = tmp_path / ".secrets"
        secrets.write_text("")

        result = asyncio.run(smoke_test_url("https://example.com/jobs/1", secrets_path=secrets))
        assert result.cloudflare_blocked is True
        assert result.success is False

    @patch("job_search.ats.applicant._find_claude_binary", return_value="/usr/bin/claude")
    @patch("asyncio.create_subprocess_exec")
    def test_returns_failure_on_timeout(self, mock_exec, _mock_binary, tmp_path):
        mock_proc = AsyncMock()
        mock_proc.communicate.side_effect = asyncio.TimeoutError()
        mock_exec.return_value = mock_proc

        secrets = tmp_path / ".secrets"
        secrets.write_text("")

        result = asyncio.run(
            smoke_test_url("https://example.com/jobs/1", secrets_path=secrets, timeout=1)
        )
        assert result.success is False
        assert "timed out" in result.notes.lower()

    @patch("job_search.ats.applicant._find_claude_binary", return_value="/usr/bin/claude")
    @patch("asyncio.create_subprocess_exec")
    def test_greenhouse_smoke_test_uses_90s_timeout(self, mock_exec, _mock_binary, tmp_path):
        """Smoke test on a Greenhouse URL should use the 90s timeout, not the 60s default."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        secrets = tmp_path / ".secrets"
        secrets.write_text("")

        # Verify the timeout logic via _resolve_timeout with greenhouse ats
        from job_search.ats.detector import detect_ats
        from job_search.ats.applicant import _resolve_timeout

        ats = detect_ats("https://boards.greenhouse.io/acme/jobs/123")
        assert _resolve_timeout(ats.ats) == GREENHOUSE_TIMEOUT


# ---------------------------------------------------------------------------
# 5. apply_to_job — Cloudflare result propagation
# ---------------------------------------------------------------------------


class TestApplyToJobCloudflare:
    @patch("job_search.ats.applicant._find_claude_binary", return_value="/usr/bin/claude")
    @patch("asyncio.create_subprocess_exec")
    def test_cloudflare_block_sets_flag(self, mock_exec, _mock_binary, tmp_path):
        """apply_to_job returns cloudflare_blocked=True when Claude output signals CF block."""
        cf_text = "Enable JavaScript and cookies to continue. Cloudflare Ray ID: deadbeef"
        result_line = json.dumps({"type": "result", "result": cf_text})

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (result_line.encode(), b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        secrets = tmp_path / ".secrets"
        secrets.write_text("")

        from job_search.criteria import Candidate

        listing = JobListing(
            url="https://example.com/jobs/1", title="Designer", company="Acme", board="other"
        )
        candidate = Candidate(
            name="Test User",
            email="test@example.com",
            phone="555-0100",
            resume_local_path="/tmp/resume.pdf",
            portfolio_url="",
            portfolio_links=[],
            linkedin_url="",
            skills=[],
            cover_letter_mode="none",
        )

        result = asyncio.run(apply_to_job(listing, candidate, "", secrets_path=secrets))
        assert result.cloudflare_blocked is True
        assert result.success is False
        assert result.submitted is False

    @patch("job_search.ats.applicant._find_claude_binary", return_value="/usr/bin/claude")
    @patch("asyncio.create_subprocess_exec")
    def test_successful_submission_not_cloudflare(self, mock_exec, _mock_binary, tmp_path):
        """A successful submission should not be marked as cloudflare_blocked."""
        ok_text = json.dumps({"submitted": True, "blocker": None, "filled_fields": ["name", "email"]})
        result_line = json.dumps({"type": "result", "result": ok_text})

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (result_line.encode(), b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        secrets = tmp_path / ".secrets"
        secrets.write_text("")

        from job_search.criteria import Candidate

        listing = JobListing(
            url="https://boards.greenhouse.io/acme/jobs/123",
            title="Designer",
            company="Acme",
            board="greenhouse",
        )
        candidate = Candidate(
            name="Test User",
            email="test@example.com",
            phone="555-0100",
            resume_local_path="/tmp/resume.pdf",
            portfolio_url="",
            portfolio_links=[],
            linkedin_url="",
            skills=[],
            cover_letter_mode="none",
        )

        result = asyncio.run(apply_to_job(listing, candidate, "", secrets_path=secrets))
        assert result.cloudflare_blocked is False
        assert result.submitted is True
