"""Notion logging for job application tracking via REST API."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from bridge.paths import data_root

from .boards.base import JobListing

log = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
SECRETS_PATH = data_root() / ".secrets"


@dataclass
class NotionLogResult:
    success: bool
    page_id: str | None
    error: str | None = None


def _load_notion_token(secrets_path: Path = SECRETS_PATH) -> str:
    """Load notion_api_token from .secrets file."""
    if not secrets_path.exists():
        return ""
    for line in secrets_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("notion_api_token="):
            return line.split("=", 1)[1].strip()
    return ""


class NotionNotifier:
    """Logs job listings to Notion Job Applications database via REST API."""

    def __init__(self, database_id: str = "", token: str = "") -> None:
        self.database_id = database_id
        self._token = token or _load_notion_token()
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            if not self._token:
                raise RuntimeError("No Notion API token configured")
            self._client = httpx.Client(
                base_url=NOTION_API_BASE,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Notion-Version": NOTION_VERSION,
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    def _build_page_properties(
        self, listing: JobListing, ats: str = "", cover_letter: str = ""
    ) -> dict:
        """Build Notion page properties from a JobListing."""
        props: dict = {
            "Title": {"title": [{"text": {"content": listing.title}}]},
            "Company": {"rich_text": [{"text": {"content": listing.company}}]},
            "URL": {"url": listing.url},
            "Board": {"select": {"name": listing.board or "unknown"}},
            "Status": {"select": {"name": "New"}},
        }
        if ats and ats != "unknown":
            props["ATS"] = {"select": {"name": ats}}
        if listing.compensation:
            props["Compensation"] = {
                "rich_text": [{"text": {"content": listing.compensation}}]
            }
        if listing.location:
            props["Location"] = {
                "rich_text": [{"text": {"content": listing.location}}]
            }
        return props

    async def log_listing(
        self, listing: JobListing, ats: str = "", cover_letter: str = ""
    ) -> NotionLogResult:
        """Create a page in the Notion Job Applications DB for a new listing."""
        if not self.database_id:
            return NotionLogResult(success=False, page_id=None, error="No database_id configured")

        if not self._token:
            log.warning("No Notion API token — skipping log for '%s'", listing.title)
            return NotionLogResult(success=False, page_id=None, error="No Notion API token")

        try:
            client = self._get_client()
            properties = self._build_page_properties(listing, ats=ats, cover_letter=cover_letter)

            body: dict = {
                "parent": {"database_id": self.database_id},
                "properties": properties,
            }

            # Add description as page content if present
            children = []
            if listing.description:
                desc = listing.description[:2000]
                children.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"text": {"content": desc}}]
                    },
                })
            if cover_letter:
                children.append({
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"text": {"content": "Cover Letter"}}]
                    },
                })
                children.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"text": {"content": cover_letter[:2000]}}]
                    },
                })

            if children:
                body["children"] = children

            resp = client.post("/pages", json=body)
            resp.raise_for_status()
            data = resp.json()
            page_id = data.get("id", "")

            log.info("Notion page created for '%s' @ %s — page_id=%s", listing.title, listing.company, page_id)
            return NotionLogResult(success=True, page_id=page_id)

        except httpx.HTTPStatusError as e:
            error_msg = f"Notion API {e.response.status_code}: {e.response.text[:200]}"
            log.error("Notion log failed for '%s': %s", listing.title, error_msg)
            return NotionLogResult(success=False, page_id=None, error=error_msg)
        except Exception as e:
            error_msg = str(e)
            log.error("Notion log failed for '%s': %s", listing.title, error_msg)
            return NotionLogResult(success=False, page_id=None, error=error_msg)

    async def update_status(
        self, page_id: str, status: str, applied_at: str = ""
    ) -> NotionLogResult:
        """Update application status in Notion."""
        if not self._token:
            return NotionLogResult(success=False, page_id=page_id, error="No Notion API token")

        try:
            client = self._get_client()
            properties: dict = {
                "Status": {"select": {"name": status}},
            }
            if applied_at:
                properties["Applied At"] = {"date": {"start": applied_at}}

            resp = client.patch(f"/pages/{page_id}", json={"properties": properties})
            resp.raise_for_status()

            log.info("Notion page %s updated to status=%s", page_id, status)
            return NotionLogResult(success=True, page_id=page_id)

        except httpx.HTTPStatusError as e:
            error_msg = f"Notion API {e.response.status_code}: {e.response.text[:200]}"
            log.error("Notion update failed for page %s: %s", page_id, error_msg)
            return NotionLogResult(success=False, page_id=page_id, error=error_msg)
        except Exception as e:
            log.error("Notion update failed for page %s: %s", page_id, e)
            return NotionLogResult(success=False, page_id=page_id, error=str(e))

    def update_status_sync(self, page_id: str, status: str) -> NotionLogResult:
        """Synchronous status update (for use from non-async execution code)."""
        if not self._token:
            return NotionLogResult(success=False, page_id=page_id, error="No Notion API token")
        try:
            client = self._get_client()
            resp = client.patch(
                f"/pages/{page_id}",
                json={"properties": {"Status": {"select": {"name": status}}}},
            )
            resp.raise_for_status()
            return NotionLogResult(success=True, page_id=page_id)
        except Exception as e:
            log.error("Notion sync update failed for page %s: %s", page_id, e)
            return NotionLogResult(success=False, page_id=page_id, error=str(e))
