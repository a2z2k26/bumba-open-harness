"""Tests for outreach research and email drafting."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch

from job_search.outreach import (
    Contact,
    OutreachDraft,
    _build_research_prompt,
    _build_draft_prompt,
    _extract_result_text,
    _parse_contacts_json,
    _parse_email_draft,
    draft_outreach_email,
    research_decision_makers,
)
from job_search.boards.base import JobListing
from job_search.criteria import Candidate


@pytest.fixture
def sample_listing():
    return JobListing(
        url="https://example.com/jobs/1",
        title="Senior Designer",
        company="Acme Corp",
        board="weworkremotely",
        location="Remote",
        compensation="$120k",
        description="Design stuff",
    )


@pytest.fixture
def sample_candidate():
    return Candidate(
        name="Test User",
        email="test@example.com",
        phone="555-0100",
        resume_local_path="/tmp/resume.pdf",
        portfolio_url="https://portfolio.example.com",
        portfolio_links=["https://portfolio.example.com"],
        linkedin_url="https://linkedin.com/in/testuser",
        skills=["Python", "Design", "UX", "React", "TypeScript"],
        cover_letter_mode="ai_generated",
    )


@pytest.fixture
def sample_contact():
    return Contact(
        name="Jane Smith",
        title="CTO",
        email="jane@acme.com",
        company="Acme Corp",
        hook="Recently launched v2.0 of their design system",
    )


class TestContactDataclass:
    def test_fields(self, sample_contact):
        assert sample_contact.name == "Jane Smith"
        assert sample_contact.title == "CTO"
        assert sample_contact.email == "jane@acme.com"
        assert sample_contact.company == "Acme Corp"
        assert sample_contact.hook == "Recently launched v2.0 of their design system"


class TestOutreachDraftDataclass:
    def test_fields(self, sample_contact):
        draft = OutreachDraft(
            contact=sample_contact,
            subject="Re: Senior Designer role",
            body="Dear Jane...",
            slot=1,
        )
        assert draft.contact == sample_contact
        assert draft.subject == "Re: Senior Designer role"
        assert draft.slot == 1


class TestBuildResearchPrompt:
    def test_includes_company(self):
        prompt = _build_research_prompt("Acme Corp", "https://acme.com/jobs/1", "Senior Designer")
        assert "Acme Corp" in prompt
        assert "Senior Designer" in prompt
        assert "https://acme.com/jobs/1" in prompt
        assert "2 decision-makers" in prompt


class TestBuildDraftPrompt:
    def test_includes_all_info(self, sample_contact, sample_listing, sample_candidate):
        prompt = _build_draft_prompt(sample_contact, sample_listing, sample_candidate)
        assert "Jane Smith" in prompt
        assert "CTO" in prompt
        assert "Acme Corp" in prompt
        assert "Senior Designer" in prompt
        assert "Test User" in prompt
        assert "design system" in prompt


class TestParseContactsJson:
    def test_valid_json_array(self):
        text = json.dumps([
            {"name": "Jane Smith", "title": "CTO", "email": "jane@acme.com", "hook": "Blog post"},
            {"name": "Bob Jones", "title": "VP Eng", "email": "bob@acme.com", "hook": "Conference"},
        ])
        contacts = _parse_contacts_json(text, "Acme Corp")
        assert len(contacts) == 2
        assert contacts[0].name == "Jane Smith"
        assert contacts[0].company == "Acme Corp"
        assert contacts[1].name == "Bob Jones"

    def test_json_in_code_fence(self):
        text = '```json\n[{"name": "Jane", "title": "CTO", "email": "j@a.com", "hook": "x"}]\n```'
        contacts = _parse_contacts_json(text, "Acme")
        assert len(contacts) == 1
        assert contacts[0].name == "Jane"

    def test_json_with_surrounding_text(self):
        text = 'Here are the contacts:\n[{"name": "Jane", "title": "CTO", "email": "j@a.com"}]\nDone!'
        contacts = _parse_contacts_json(text, "Acme")
        assert len(contacts) == 1

    def test_max_two_contacts(self):
        data = [
            {"name": f"Person {i}", "title": "VP", "email": f"p{i}@a.com", "hook": "x"}
            for i in range(5)
        ]
        contacts = _parse_contacts_json(json.dumps(data), "Acme")
        assert len(contacts) == 2

    def test_skips_entries_without_name(self):
        text = json.dumps([{"title": "CTO", "email": "j@a.com"}])
        contacts = _parse_contacts_json(text, "Acme")
        assert len(contacts) == 0

    def test_skips_entries_without_email(self):
        text = json.dumps([{"name": "Jane", "title": "CTO"}])
        contacts = _parse_contacts_json(text, "Acme")
        assert len(contacts) == 0

    def test_invalid_json_returns_empty(self):
        contacts = _parse_contacts_json("not json at all", "Acme")
        assert contacts == []

    def test_empty_hook_defaults(self):
        text = json.dumps([{"name": "Jane", "title": "CTO", "email": "j@a.com"}])
        contacts = _parse_contacts_json(text, "Acme")
        assert contacts[0].hook == ""

    def test_non_list_json_returns_empty(self):
        contacts = _parse_contacts_json('{"name": "Jane"}', "Acme")
        assert contacts == []


class TestParseEmailDraft:
    def test_standard_format(self):
        text = "SUBJECT: Quick intro re: Designer role\n\nHi Jane,\n\nI noticed your design system launch..."
        subject, body = _parse_email_draft(text)
        assert subject == "Quick intro re: Designer role"
        assert "Hi Jane" in body

    def test_lowercase_subject(self):
        text = "subject: Hello\n\nBody here"
        subject, body = _parse_email_draft(text)
        assert subject == "Hello"
        assert "Body here" in body

    def test_code_fence_wrapper(self):
        text = "```\nSUBJECT: Test\n\nBody\n```"
        subject, body = _parse_email_draft(text)
        assert subject == "Test"

    def test_empty_text(self):
        subject, body = _parse_email_draft("")
        assert subject == ""
        assert body == ""


class TestExtractResultText:
    def test_extracts_result_type(self):
        lines = [
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "thinking..."}]}}),
            json.dumps({"type": "result", "result": "final answer"}),
        ]
        result = _extract_result_text("\n".join(lines))
        assert result == "final answer"

    def test_falls_back_to_last_assistant_text(self):
        lines = [
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "first"}]}}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "second"}]}}),
        ]
        result = _extract_result_text("\n".join(lines))
        assert result == "second"

    def test_empty_stdout(self):
        result = _extract_result_text("")
        assert result is None

    def test_invalid_json_lines_skipped(self):
        lines = [
            "not json",
            json.dumps({"type": "result", "result": "ok"}),
        ]
        result = _extract_result_text("\n".join(lines))
        assert result == "ok"


class TestResearchDecisionMakers:
    @patch("job_search.outreach._find_claude_binary", side_effect=FileNotFoundError("not found"))
    def test_returns_empty_if_no_binary(self, mock_binary):
        result = asyncio.run(research_decision_makers("Acme", "https://acme.com", "Designer"))
        assert result == []

    @patch("job_search.outreach._find_claude_binary", return_value="/usr/bin/claude")
    @patch("asyncio.create_subprocess_exec")
    def test_returns_contacts_on_success(self, mock_exec, mock_binary, tmp_path):
        contacts_json = json.dumps([
            {"name": "Jane", "title": "CTO", "email": "jane@acme.com", "hook": "blog"},
        ])
        result_line = json.dumps({"type": "result", "result": contacts_json})

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (result_line.encode(), b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        secrets = tmp_path / ".secrets"
        secrets.write_text("claude_oauth_token=test-token\n")

        result = asyncio.run(research_decision_makers(
            "Acme", "https://acme.com", "Designer",
            secrets_path=secrets,
        ))
        assert len(result) == 1
        assert result[0].name == "Jane"

    @patch("job_search.outreach._find_claude_binary", return_value="/usr/bin/claude")
    @patch("asyncio.create_subprocess_exec")
    def test_returns_empty_on_nonzero_exit(self, mock_exec, mock_binary, tmp_path):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"error")
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        secrets = tmp_path / ".secrets"
        secrets.write_text("")

        result = asyncio.run(research_decision_makers(
            "Acme", "https://acme.com", "Designer",
            secrets_path=secrets,
        ))
        assert result == []

    @patch("job_search.outreach._find_claude_binary", return_value="/usr/bin/claude")
    @patch("asyncio.create_subprocess_exec")
    def test_returns_empty_on_timeout(self, mock_exec, mock_binary, tmp_path):
        mock_proc = AsyncMock()
        mock_proc.communicate.side_effect = asyncio.TimeoutError()
        mock_exec.return_value = mock_proc

        secrets = tmp_path / ".secrets"
        secrets.write_text("")

        result = asyncio.run(research_decision_makers(
            "Acme", "https://acme.com", "Designer",
            secrets_path=secrets, timeout=1,
        ))
        assert result == []


class TestDraftOutreachEmail:
    @patch("job_search.outreach._find_claude_binary", side_effect=FileNotFoundError("not found"))
    def test_returns_none_if_no_binary(self, mock_binary, sample_contact, sample_listing, sample_candidate):
        result = asyncio.run(draft_outreach_email(sample_contact, sample_listing, sample_candidate))
        assert result is None

    @patch("job_search.outreach._find_claude_binary", return_value="/usr/bin/claude")
    @patch("asyncio.create_subprocess_exec")
    def test_returns_draft_on_success(self, mock_exec, mock_binary, sample_contact, sample_listing, sample_candidate, tmp_path):
        email_text = "SUBJECT: Quick intro\n\nHi Jane,\n\nGreat work on the design system."
        result_line = json.dumps({"type": "result", "result": email_text})

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (result_line.encode(), b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        secrets = tmp_path / ".secrets"
        secrets.write_text("claude_oauth_token=test-token\n")

        result = asyncio.run(draft_outreach_email(
            sample_contact, sample_listing, sample_candidate,
            secrets_path=secrets,
        ))
        assert result is not None
        assert result.subject == "Quick intro"
        assert "design system" in result.body
        assert result.contact == sample_contact

    @patch("job_search.outreach._find_claude_binary", return_value="/usr/bin/claude")
    @patch("asyncio.create_subprocess_exec")
    def test_returns_none_on_empty_result(self, mock_exec, mock_binary, sample_contact, sample_listing, sample_candidate, tmp_path):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        secrets = tmp_path / ".secrets"
        secrets.write_text("")

        result = asyncio.run(draft_outreach_email(
            sample_contact, sample_listing, sample_candidate,
            secrets_path=secrets,
        ))
        assert result is None
