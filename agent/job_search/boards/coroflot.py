"""Coroflot job board scraper — HTML regex extraction.

Coroflot renders job listings as server-side HTML inside
``<ul class="listing_jobs" id="job_listings">``.
Each item is ``<li data-c-asset-id="ID">`` containing:
  - ``<a href="https://www.coroflot.com/design-jobs/SLUG-ID" data-job-id="ID">``
  - ``<div class="company_name">Company</div>``
  - ``<div class="job_title">Title</div>``
  - ``<span class="loc">Location</span>``

No JSON-LD or __NEXT_DATA__ is present as of March 2026.
"""
from __future__ import annotations

import logging
import re

import aiohttp

from .base import JobBoard, JobListing

log = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
_JOBS_URL = "https://www.coroflot.com/design-jobs"
_BASE_URL = "https://www.coroflot.com"

# Each job item is an <li data-c-asset-id="...">
_ITEM_RE = re.compile(
    r'<li\s+data-c-asset-id="(\d+)"[^>]*>(.*?)</li>',
    re.DOTALL,
)

# Within each item, extract fields
_LINK_RE = re.compile(
    r'<a\s+href="(https?://[^"]*coroflot\.com/design-jobs/[^"]+)"[^>]*data-job-id="(\d+)"',
    re.DOTALL,
)
_COMPANY_RE = re.compile(
    r'<div\s+class="company_name">\s*(.*?)\s*</div>', re.DOTALL
)
_TITLE_RE = re.compile(
    r'<div\s+class="job_title">\s*(.*?)\s*</div>', re.DOTALL
)
_LOCATION_RE = re.compile(
    r'<span\s+class="loc">\s*(.*?)\s*</span>', re.DOTALL
)


class CoroflotBoard(JobBoard):
    name = "coroflot"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.coroflot.com/",
        }

        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(_JOBS_URL) as resp:
                    resp.raise_for_status()
                    html = await resp.text()
        except Exception as exc:
            log.warning("CoroflotBoard: HTTP error fetching jobs page: %s", exc)
            return []

        listings = self._parse_html(html)

        if not listings:
            log.warning("CoroflotBoard: could not parse any listings from page")
            return []

        filtered = _keyword_filter(listings, keywords)
        log.info("Coroflot: %d listings after keyword filter", len(filtered))
        return filtered

    def _parse_html(self, html: str) -> list[JobListing]:
        """Parse job listings from Coroflot's server-rendered HTML."""
        listings: list[JobListing] = []

        for item_match in _ITEM_RE.finditer(html):
            asset_id = item_match.group(1)
            block = item_match.group(2)

            link_m = _LINK_RE.search(block)
            url = link_m.group(1) if link_m else f"{_BASE_URL}/design-jobs/{asset_id}"

            company_m = _COMPANY_RE.search(block)
            company = _strip_tags(company_m.group(1)) if company_m else ""

            title_m = _TITLE_RE.search(block)
            title = _strip_tags(title_m.group(1)) if title_m else ""

            location_m = _LOCATION_RE.search(block)
            loc = _strip_tags(location_m.group(1)) if location_m else ""

            is_remote = bool(re.search(r'\bremote\b', block, re.IGNORECASE))

            listings.append(
                JobListing(
                    url=url,
                    title=title,
                    company=company,
                    board=self.name,
                    location=loc,
                    remote="remote" if is_remote else "",
                    compensation="",
                    description="",
                    raw={"asset_id": asset_id},
                )
            )

        return listings


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _keyword_filter(listings: list[JobListing], keywords: list[str]) -> list[JobListing]:
    if not keywords:
        return listings
    lower_kw = [kw.lower() for kw in keywords]
    return [
        j for j in listings
        if any(kw in j.title.lower() or kw in j.company.lower() for kw in lower_kw)
    ]
