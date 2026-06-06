"""Tests for Notion notifier REST API integration."""
import pytest
from unittest.mock import patch, MagicMock

from job_search.notifier import NotionNotifier, _load_notion_token
from job_search.boards.base import JobListing


def _make_listing(**overrides) -> JobListing:
    defaults = {
        "url": "https://example.com/jobs/1",
        "title": "Senior Designer",
        "company": "Acme Corp",
        "board": "weworkremotely",
        "location": "Remote",
        "compensation": "$180k",
        "description": "Great job",
    }
    defaults.update(overrides)
    return JobListing(**defaults)


class TestLoadToken:
    def test_loads_from_secrets_file(self, tmp_path):
        secrets = tmp_path / ".secrets"
        secrets.write_text("other_key=abc\nnotion_api_token=ntn_test123\n")
        assert _load_notion_token(secrets) == "ntn_test123"

    def test_returns_empty_when_no_file(self, tmp_path):
        assert _load_notion_token(tmp_path / "nonexistent") == ""

    def test_returns_empty_when_key_missing(self, tmp_path):
        secrets = tmp_path / ".secrets"
        secrets.write_text("some_other_key=value\n")
        assert _load_notion_token(secrets) == ""


class TestNotionNotifierLogListing:
    @pytest.mark.asyncio
    async def test_successful_page_creation(self):
        notifier = NotionNotifier(database_id="db-123", token="ntn_test")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "page-abc-123"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        notifier._client = mock_client

        listing = _make_listing()
        result = await notifier.log_listing(listing, ats="greenhouse")

        assert result.success is True
        assert result.page_id == "page-abc-123"
        assert result.error is None

        # Verify the POST call
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/pages"
        body = call_args[1]["json"]
        assert body["parent"]["database_id"] == "db-123"
        props = body["properties"]
        assert props["Title"]["title"][0]["text"]["content"] == "Senior Designer"
        assert props["Company"]["rich_text"][0]["text"]["content"] == "Acme Corp"
        assert props["ATS"]["select"]["name"] == "greenhouse"
        assert props["Status"]["select"]["name"] == "New"

    @pytest.mark.asyncio
    async def test_no_database_id(self):
        notifier = NotionNotifier(database_id="", token="ntn_test")
        result = await notifier.log_listing(_make_listing())
        assert result.success is False
        assert "No database_id" in result.error

    @pytest.mark.asyncio
    @patch("job_search.notifier._load_notion_token", return_value="")
    async def test_no_token(self, mock_load):
        notifier = NotionNotifier(database_id="db-123", token="")
        result = await notifier.log_listing(_make_listing())
        assert result.success is False
        assert "No Notion API token" in result.error

    @pytest.mark.asyncio
    async def test_http_error_handled(self):
        import httpx

        notifier = NotionNotifier(database_id="db-123", token="ntn_test")

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=mock_response
        )
        notifier._client = mock_client

        result = await notifier.log_listing(_make_listing())
        assert result.success is False
        assert "401" in result.error

    @pytest.mark.asyncio
    async def test_unknown_ats_not_included(self):
        notifier = NotionNotifier(database_id="db-123", token="ntn_test")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "page-1"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        notifier._client = mock_client

        await notifier.log_listing(_make_listing(), ats="unknown")
        body = mock_client.post.call_args[1]["json"]
        assert "ATS" not in body["properties"]

    @pytest.mark.asyncio
    async def test_cover_letter_included_in_children(self):
        notifier = NotionNotifier(database_id="db-123", token="ntn_test")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "page-1"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        notifier._client = mock_client

        await notifier.log_listing(_make_listing(), cover_letter="Dear hiring manager...")
        body = mock_client.post.call_args[1]["json"]
        children = body.get("children", [])
        # Should have description paragraph + heading + cover letter paragraph
        assert len(children) == 3
        assert children[1]["type"] == "heading_2"


class TestNotionNotifierUpdateStatus:
    @pytest.mark.asyncio
    async def test_successful_update(self):
        notifier = NotionNotifier(database_id="db-123", token="ntn_test")

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.patch.return_value = mock_resp
        notifier._client = mock_client

        result = await notifier.update_status("page-123", "Applied", applied_at="2026-03-06")
        assert result.success is True

        call_args = mock_client.patch.call_args
        assert "/pages/page-123" in call_args[0][0]
        body = call_args[1]["json"]
        assert body["properties"]["Status"]["select"]["name"] == "Applied"
        assert body["properties"]["Applied At"]["date"]["start"] == "2026-03-06"

    @pytest.mark.asyncio
    @patch("job_search.notifier._load_notion_token", return_value="")
    async def test_no_token_returns_error(self, mock_load):
        notifier = NotionNotifier(database_id="db-123", token="")
        result = await notifier.update_status("page-123", "Applied")
        assert result.success is False
