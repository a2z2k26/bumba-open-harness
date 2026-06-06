"""Tests for cover letter generation via Claude subprocess."""
import json
import pytest
from unittest.mock import AsyncMock, patch

from job_search.cover_letter import (
    generate_cover_letter,
    _build_prompt,
    _extract_result_text,
    _load_oauth_token,
)
from job_search.boards.base import JobListing
from job_search.criteria import Candidate


def _listing(**kw) -> JobListing:
    defaults = {
        "url": "https://example.com/jobs/1",
        "title": "Senior Product Designer",
        "company": "Acme Corp",
        "board": "weworkremotely",
        "description": "We're looking for a senior designer to lead our product team.",
    }
    defaults.update(kw)
    return JobListing(**defaults)


def _candidate(**kw) -> Candidate:
    defaults = {
        "name": "Example User",
        "skills": ["Product Design", "UX Design", "Figma"],
        "portfolio_url": "https://portfolio.example.com",
        "linkedin_url": "https://www.linkedin.com/in/example-operator",
    }
    c = Candidate()
    for k, v in {**defaults, **kw}.items():
        setattr(c, k, v)
    return c


class TestBuildPrompt:
    def test_includes_job_details(self):
        prompt = _build_prompt(_listing(), _candidate())
        assert "Senior Product Designer" in prompt
        assert "Acme Corp" in prompt
        assert "looking for a senior designer" in prompt

    def test_includes_candidate_details(self):
        prompt = _build_prompt(_listing(), _candidate())
        assert "Example User" in prompt
        assert "Product Design" in prompt
        assert "example-operator.com" in prompt

    def test_truncates_long_description(self):
        listing = _listing(description="x" * 5000)
        prompt = _build_prompt(listing, _candidate())
        # Description should be truncated to 2000 chars — full 5000 should NOT appear
        assert "x" * 5000 not in prompt
        assert "x" * 2000 in prompt


class TestExtractResultText:
    def test_extracts_from_result_event(self):
        lines = [
            json.dumps({"type": "system", "subtype": "init", "session_id": "abc"}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "partial"}]}}),
            json.dumps({"type": "result", "result": "Dear Hiring Manager,\n\nFull letter here.", "is_error": False}),
        ]
        stdout = "\n".join(lines)
        text = _extract_result_text(stdout)
        assert text == "Dear Hiring Manager,\n\nFull letter here."

    def test_falls_back_to_assistant_text(self):
        lines = [
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Dear HM..."}]}}),
            json.dumps({"type": "result", "result": "", "is_error": False}),
        ]
        stdout = "\n".join(lines)
        text = _extract_result_text(stdout)
        assert text == "Dear HM..."

    def test_returns_none_for_empty(self):
        assert _extract_result_text("") is None
        assert _extract_result_text("not json\n") is None


class TestLoadOAuthToken:
    def test_loads_token(self, tmp_path):
        secrets = tmp_path / ".secrets"
        secrets.write_text("claude_oauth_token=tok_abc123\n")
        assert _load_oauth_token(secrets) == "tok_abc123"

    def test_missing_file(self, tmp_path):
        assert _load_oauth_token(tmp_path / "nope") == ""


class TestGenerateCoverLetter:
    @pytest.mark.asyncio
    async def test_successful_generation(self, tmp_path):
        secrets = tmp_path / ".secrets"
        secrets.write_text("claude_oauth_token=test\n")

        result_json = json.dumps({
            "type": "result",
            "result": "Dear Hiring Manager,\n\nGreat letter content.",
            "is_error": False,
        })

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (result_json.encode(), b"")
        mock_proc.returncode = 0

        with patch("job_search.cover_letter._find_claude_binary", return_value="/usr/local/bin/claude"), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            text = await generate_cover_letter(
                _listing(), _candidate(), secrets_path=secrets
            )

        assert text is not None
        assert "Dear Hiring Manager" in text

    @pytest.mark.asyncio
    async def test_subprocess_failure(self, tmp_path):
        secrets = tmp_path / ".secrets"
        secrets.write_text("claude_oauth_token=test\n")

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"auth error")
        mock_proc.returncode = 1

        with patch("job_search.cover_letter._find_claude_binary", return_value="/usr/local/bin/claude"), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            text = await generate_cover_letter(
                _listing(), _candidate(), secrets_path=secrets
            )

        assert text is None

    @pytest.mark.asyncio
    async def test_binary_not_found(self, tmp_path):
        secrets = tmp_path / ".secrets"
        secrets.write_text("")

        with patch("job_search.cover_letter._find_claude_binary", side_effect=FileNotFoundError("not found")):
            text = await generate_cover_letter(
                _listing(), _candidate(), secrets_path=secrets
            )
        assert text is None
