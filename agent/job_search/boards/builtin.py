"""Built In board scraper — HTML regex extraction from remote design listings page.

Built In renders job listings as server-side HTML with ``<div id="job-card-ID"
data-id="job-card" ...>`` elements.  Each card contains:
  - ``<a ... data-id="company-title" ...><span>Company</span></a>``
  - ``<a href="/job/SLUG/ID" ... data-id="job-card-title" ...>Title</a>``
  - Salary text near ``fa-sack-dollar`` icon
  - Location from ``aria-label="Job locations"``
  - Remote indicator near ``fa-house-building`` icon
  - Description in ``<div class="fs-sm fw-regular mb-md text-gray-04">``

No JSON-LD is present as of March 2026.
"""
from __future__ import annotations

import html as htmlmod
import logging
import re

import aiohttp

from .base import JobBoard, JobListing

log = logging.getLogger(__name__)

_PAGE_URL = "https://builtin.com/jobs/remote/design"
_BASE_URL = "https://builtin.com"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# Within each card window, extract fields.
# Note: href comes BEFORE data-id in the actual HTML.
_COMPANY_RE = re.compile(
    r'data-id="company-title"[^>]*>\s*<span>\s*(.*?)\s*</span>\s*</a>',
    re.DOTALL,
)
_TITLE_RE = re.compile(
    r'href="(/job/[^"]*)"[^>]*data-id="job-card-title"[^>]*>(.*?)</a>',
    re.DOTALL,
)
# Salary: fa-sack-dollar icon in <i>, then </i></div>\n<span class="font-barlow ...">VALUE</span>
_SALARY_RE = re.compile(
    r'fa-sack-dollar[^>]*>.*?</i>\s*</div>\s*<span[^>]*>\s*(.*?)\s*</span>',
    re.DOTALL,
)
# Remote: fa-house-building icon in <i>, then </i></div>\n<span>Remote</span>
_REMOTE_RE = re.compile(
    r'fa-house-building[^>]*>.*?</i>\s*</div>\s*<span[^>]*>\s*(.*?)\s*</span>',
    re.DOTALL,
)
# Location from aria-label tooltip (handles multi-location cards)
_LOCATION_ARIA_RE = re.compile(
    r'aria-label="Job locations"[^>]*data-bs-title="(.*?)"',
    re.DOTALL,
)
# Single location: fa-location-dot icon followed by span
_LOCATION_SINGLE_RE = re.compile(
    r'fa-location-dot[^>]*>.*?</i>\s*</div>\s*(?:</div>\s*)?<(?:div>)?\s*<span[^>]*>\s*(.*?)\s*</span>',
    re.DOTALL,
)
# Description snippet
_DESC_RE = re.compile(
    r'class="fs-sm\s+fw-regular\s+mb-md\s+text-gray-04">\s*(.*?)\s*</div>',
    re.DOTALL,
)


class BuiltInBoard(JobBoard):
    name = "builtin"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        """Fetch Built In remote/design page and extract job cards from HTML."""
        headers = {"User-Agent": _USER_AGENT}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    _PAGE_URL,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    resp.raise_for_status()
                    html = await resp.text()
        except Exception as exc:
            log.error("BuiltIn fetch failed: %s", exc)
            return []

        return self._parse(html, keywords)

    def _parse(self, html: str, keywords: list[str]) -> list[JobListing]:
        """Extract job listings from Built In's server-rendered HTML."""
        listings: list[JobListing] = []
        kw_lower = [kw.lower() for kw in keywords]

        # Find each job-card-ID and extract a generous window
        card_ids = re.findall(r'<div\s+id="job-card-(\d+)"', html)
        if not card_ids:
            log.warning("BuiltIn: no job cards found in page")
            return []

        for i, card_id in enumerate(card_ids):
            marker = f'id="job-card-{card_id}"'
            pos = html.find(marker)
            if pos == -1:
                continue

            # Determine card window: from this card to the next, or +6000 chars
            if i + 1 < len(card_ids):
                next_marker = f'id="job-card-{card_ids[i + 1]}"'
                next_pos = html.find(next_marker, pos + 1)
                if next_pos > pos:
                    block = html[pos:next_pos]
                else:
                    block = html[pos:pos + 6000]
            else:
                block = html[pos:pos + 6000]

            # Company
            company_m = _COMPANY_RE.search(block)
            company = _strip_tags(company_m.group(1)) if company_m else ""

            # Title and URL
            title_m = _TITLE_RE.search(block)
            if not title_m:
                continue
            job_path = title_m.group(1)
            title = _strip_tags(title_m.group(2))
            url = f"{_BASE_URL}{job_path}"

            # Salary
            salary_m = _SALARY_RE.search(block)
            compensation = _strip_tags(salary_m.group(1)) if salary_m else ""

            # Location: try multi-location tooltip first, then single location
            location_str = ""
            loc_aria_m = _LOCATION_ARIA_RE.search(block)
            if loc_aria_m:
                raw_loc = htmlmod.unescape(loc_aria_m.group(1))
                # Strip HTML tags and join with commas
                parts = re.split(r'<[^>]+>', raw_loc)
                location_str = ", ".join(p.strip() for p in parts if p.strip())
            else:
                loc_single_m = _LOCATION_SINGLE_RE.search(block)
                if loc_single_m:
                    location_str = _strip_tags(loc_single_m.group(1))

            # Remote
            remote_m = _REMOTE_RE.search(block)
            remote_text = _strip_tags(remote_m.group(1)).lower() if remote_m else ""
            is_remote = "remote" in remote_text or "remote" in location_str.lower()

            # Description snippet
            desc_m = _DESC_RE.search(block)
            description = _strip_tags(desc_m.group(1)) if desc_m else ""

            # Keyword filter
            combined = (title + " " + company + " " + description[:300]).lower()
            if kw_lower and not any(kw in combined for kw in kw_lower):
                continue

            listings.append(JobListing(
                url=url,
                title=title,
                company=company,
                board=self.name,
                location=location_str if location_str else ("Remote" if is_remote else ""),
                remote="yes" if is_remote else "",
                compensation=compensation,
                description=description[:500],
                raw={"card_id": card_id, "job_path": job_path},
            ))

        log.info("BuiltIn: %d listings after keyword filter", len(listings))
        return listings


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()
