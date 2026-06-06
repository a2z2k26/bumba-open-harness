"""Tests for job_search tools in teams/tools/_job_search.py (sprint D5.2)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.test_teams.conftest import make_deps
from teams._tool_registry import TOOL_CALLABLES


class TestJobSearchToolsRegistration:
    """All 8 job search tools are registered in TOOL_CALLABLES."""

    EXPECTED_TOOLS = [
        "scrape_boards",
        "score_and_deduplicate",
        "generate_cover_letter",
        "stage_listing_to_notion",
        "get_approved_listings",
        "update_notion_status",
        "send_discord_alert",
        "research_contacts",
    ]

    def test_all_tools_registered(self):
        for name in self.EXPECTED_TOOLS:
            assert name in TOOL_CALLABLES, f"Tool '{name}' missing from TOOL_CALLABLES"

    def test_all_tools_are_callable(self):
        for name in self.EXPECTED_TOOLS:
            fn = TOOL_CALLABLES[name]
            assert callable(fn), f"Tool '{name}' is not callable"

    def test_tools_are_imported_from_job_search_module(self):
        from teams.tools._job_search import (
            scrape_boards,
            send_discord_alert,
            research_contacts,
        )
        assert TOOL_CALLABLES["scrape_boards"] is scrape_boards
        assert TOOL_CALLABLES["research_contacts"] is research_contacts
        assert TOOL_CALLABLES["send_discord_alert"] is send_discord_alert


class TestSendDiscordAlertFallback:
    """send_discord_alert writes a service_messages file when no event_bus."""

    @pytest.mark.asyncio
    async def test_discord_alert_uses_event_bus(self):
        from teams.tools._job_search import send_discord_alert

        mock_bus = MagicMock()
        deps = make_deps(session_id="test", department="job_search", event_bus=mock_bus)
        ctx = MagicMock()
        ctx.deps = deps

        result = await send_discord_alert(ctx, "hello from job search", source="job_search")

        assert result["success"] is True
        mock_bus.publish.assert_called_once_with(
            "discord.send", {"message": "hello from job search", "source": "job_search"}
        )


class TestGetApprovedListings:
    @pytest.mark.asyncio
    async def test_returns_empty_on_no_notion_token(self):
        from teams.tools._job_search import get_approved_listings

        deps = make_deps(session_id="test", department="job_search")
        ctx = MagicMock()
        ctx.deps = deps

        with patch("job_search.notifier._load_notion_token", return_value=""), \
             patch("job_search.approval.check_approvals", return_value=[]):
            result = await get_approved_listings(ctx)

        assert result["items"] == []
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_returns_approved_items(self):
        from teams.tools._job_search import get_approved_listings
        from job_search.approval import ApprovedItem

        deps = make_deps(session_id="test", department="job_search")
        ctx = MagicMock()
        ctx.deps = deps

        mock_items = [
            ApprovedItem(
                page_id="page-1",
                fingerprint="fp1",
                company="Acme Corp",
                apply_approved=True,
                outreach_1_approved=False,
                outreach_2_approved=False,
            )
        ]

        with patch("job_search.approval.check_approvals", return_value=mock_items):
            result = await get_approved_listings(ctx)

        assert result["count"] == 1
        assert result["items"][0]["company"] == "Acme Corp"
        assert result["items"][0]["apply_approved"] is True


class TestResearchContacts:
    @pytest.mark.asyncio
    async def test_returns_empty_on_failure(self):
        from teams.tools._job_search import research_contacts

        deps = make_deps(session_id="test", department="outreach")
        ctx = MagicMock()
        ctx.deps = deps

        with patch(
            "job_search.outreach.research_decision_makers",
            side_effect=RuntimeError("subprocess failed"),
        ):
            result = await research_contacts(ctx, "Acme", "https://example.com/job", "Designer")

        assert result["contacts"] == []
        assert result["count"] == 0
        assert "error" in result

    @pytest.mark.asyncio
    async def test_returns_contacts_on_success(self):
        from teams.tools._job_search import research_contacts
        from job_search.outreach import Contact

        deps = make_deps(session_id="test", department="outreach")
        ctx = MagicMock()
        ctx.deps = deps

        mock_contacts = [
            Contact(
                name="Jane Smith",
                title="VP Design",
                email="jane@acme.com",
                company="Acme",
                hook="Previously led design at Figma",
            )
        ]

        with patch("job_search.outreach.research_decision_makers", return_value=mock_contacts):
            result = await research_contacts(ctx, "Acme", "https://example.com/job", "Designer")

        assert result["count"] == 1
        assert result["contacts"][0]["name"] == "Jane Smith"
        assert result["contacts"][0]["email"] == "jane@acme.com"


class TestUpdateNotionStatus:
    @pytest.mark.asyncio
    async def test_returns_error_on_no_token(self):
        from teams.tools._job_search import update_notion_status
        from job_search.notifier import NotionLogResult

        deps = make_deps(session_id="test", department="job_search")
        ctx = MagicMock()
        ctx.deps = deps

        mock_result = NotionLogResult(
            success=False, page_id="page-1", error="No Notion API token"
        )

        with patch("job_search.notifier.NotionNotifier.update_status", AsyncMock(return_value=mock_result)):
            result = await update_notion_status(ctx, "page-1", "Applied")

        assert result["success"] is False
        assert "token" in (result.get("error") or "").lower()

    @pytest.mark.asyncio
    async def test_returns_success(self):
        from teams.tools._job_search import update_notion_status
        from job_search.notifier import NotionLogResult

        deps = make_deps(session_id="test", department="job_search")
        ctx = MagicMock()
        ctx.deps = deps

        mock_result = NotionLogResult(success=True, page_id="page-1")

        with patch("job_search.notifier.NotionNotifier.update_status", AsyncMock(return_value=mock_result)):
            result = await update_notion_status(ctx, "page-1", "Applied")

        assert result["success"] is True
