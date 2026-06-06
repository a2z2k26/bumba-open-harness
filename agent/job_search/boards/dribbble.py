"""Dribbble job board scraper — HTML regex extraction.

Dribbble renders job listings as server-side HTML inside ``<ol class="job-board-job-list">``
with ``<li class="job-list-item ...">`` elements.  Each card contains:
  - ``<a class="job-link" href="/jobs/ID-SLUG?source=index">`` (the job URL)
  - ``<span class="job-board-job-company">Company</span>``
  - ``<h4 class="job-title job-board-job-title">Title</h4>``
  - ``<span class="location">Location</span>``

No __NEXT_DATA__ or JSON-LD is present as of March 2026.
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
_BASE_URL = "https://dribbble.com"
_JOBS_URL = "https://dribbble.com/jobs?keyword=design&location=Anywhere"

# Matches each job list item block
_ITEM_RE = re.compile(
    r'<li\s+class="job-list-item[^"]*">(.*?)</li>',
    re.DOTALL,
)

# Within each item, extract the link, company, title, location
_LINK_RE = re.compile(r'<a\s+class="job-link"[^>]*href="(/jobs/[^"]+)"')
_COMPANY_RE = re.compile(
    r'<span\s+class="job-board-job-company">\s*(.*?)\s*</span>', re.DOTALL
)
_TITLE_RE = re.compile(
    r'<h4\s+class="[^"]*job-board-job-title[^"]*">\s*(.*?)\s*</h4>', re.DOTALL
)
_LOCATION_RE = re.compile(
    r'<span\s+class="location">\s*(.*?)\s*</span>', re.DOTALL
)


class DribbbleBoard(JobBoard):
    name = "dribbble"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {"User-Agent": _USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}

        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(_JOBS_URL) as resp:
                    resp.raise_for_status()
                    html = await resp.text()
        except Exception as exc:
            log.warning("DribbbleBoard: HTTP error fetching jobs page: %s", exc)
            return []

        listings = self._parse_html(html)

        if not listings:
            log.warning("DribbbleBoard: could not parse any listings from page")
            return []

        filtered = _keyword_filter(listings, keywords)
        log.info("Dribbble: %d listings after keyword filter", len(filtered))
        return filtered

    def _parse_html(self, html: str) -> list[JobListing]:
        """Parse job listings from Dribbble's server-rendered HTML."""
        listings: list[JobListing] = []

        for item_match in _ITEM_RE.finditer(html):
            block = item_match.group(1)

            link_m = _LINK_RE.search(block)
            if not link_m:
                continue
            path = link_m.group(1)
            # Strip ?source=index from the URL for a cleaner canonical link
            clean_path = re.sub(r'\?source=index$', '', path)
            url = f"{_BASE_URL}{clean_path}"

            company_m = _COMPANY_RE.search(block)
            company = _strip_tags(company_m.group(1)) if company_m else ""

            title_m = _TITLE_RE.search(block)
            title = _strip_tags(title_m.group(1)) if title_m else ""

            location_m = _LOCATION_RE.search(block)
            loc = _strip_tags(location_m.group(1)) if location_m else ""

            is_remote = "remote" in block.lower()

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
                    raw={"path": clean_path},
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
