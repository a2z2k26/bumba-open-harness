"""Behance job board scraper — HTML regex extraction.

Behance renders job listings as server-side HTML using CSS-module class names
(e.g. ``JobCard-jobCard-xxx``, ``JobCard-company-xxx``, ``JobCard-jobTitle-xxx``).

Each card contains:
  - ``<a href="/joblist/ID/Slug" class="JobCard-jobCardLink-xxx" aria-label="Title">``
  - ``<p class="JobCard-company-xxx">Company</p>``
  - ``<h3 class="JobCard-jobTitle-xxx">Title</h3>``
  - ``<p class="JobCard-jobLocation-xxx">Location</p>``
  - ``<p class="JobCard-jobDescription-xxx">Description snippet</p>``

No __NEXT_DATA__ is present as of March 2026.
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
_JOBS_URL = "https://www.behance.net/joblist?field=132&location=remote"
_BASE_URL = "https://www.behance.net"

# Each job card is an <li role="article"> containing a JobCard div
_CARD_RE = re.compile(
    r'<li[^>]*role="article"[^>]*>(.*?)</li>',
    re.DOTALL,
)

# Within each card, extract fields using the CSS-module prefix pattern
_LINK_RE = re.compile(
    r'<a\s+href="(/joblist/\d+/[^"]*)"[^>]*class="JobCard-jobCardLink[^"]*"[^>]*aria-label="([^"]*)"',
    re.DOTALL,
)
_COMPANY_RE = re.compile(
    r'<p\s+class="JobCard-company-[^"]*">\s*(.*?)\s*</p>', re.DOTALL
)
_LOCATION_RE = re.compile(
    r'<p\s+class="JobCard-jobLocation-[^"]*">\s*(.*?)\s*</p>', re.DOTALL
)
_TITLE_RE = re.compile(
    r'<h3\s+class="JobCard-jobTitle-[^"]*"[^>]*>\s*(.*?)\s*</h3>', re.DOTALL
)
_DESC_RE = re.compile(
    r'<p\s+class="JobCard-jobDescription-[^"]*">\s*(.*?)\s*</p>', re.DOTALL
)


class BehanceBoard(JobBoard):
    name = "behance"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(_JOBS_URL) as resp:
                    resp.raise_for_status()
                    html = await resp.text()
        except Exception as exc:
            log.warning("BehanceBoard: HTTP error fetching jobs page: %s", exc)
            return []

        listings = self._parse_html(html)

        if not listings:
            log.warning("BehanceBoard: could not parse any listings from page")
            return []

        filtered = _keyword_filter(listings, keywords)
        log.info("Behance: %d listings after keyword filter", len(filtered))
        return filtered

    def _parse_html(self, html: str) -> list[JobListing]:
        """Parse job listings from Behance's server-rendered HTML."""
        listings: list[JobListing] = []

        for card_match in _CARD_RE.finditer(html):
            block = card_match.group(1)

            link_m = _LINK_RE.search(block)
            if not link_m:
                continue
            path = link_m.group(1)
            aria_label = link_m.group(2)
            url = f"{_BASE_URL}{path}"

            # Title: prefer <h3> tag, fall back to aria-label on the link
            title_m = _TITLE_RE.search(block)
            title = _strip_tags(title_m.group(1)) if title_m else aria_label

            company_m = _COMPANY_RE.search(block)
            company = _strip_tags(company_m.group(1)) if company_m else ""

            location_m = _LOCATION_RE.search(block)
            loc = _strip_tags(location_m.group(1)) if location_m else ""

            desc_m = _DESC_RE.search(block)
            description = _strip_tags(desc_m.group(1)) if desc_m else ""

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
                    description=description[:500],
                    raw={"path": path},
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
