"""We Work Remotely board scraper — RSS feed."""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

import aiohttp

from .base import JobBoard, JobListing

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

WWR_RSS_URL = "https://weworkremotely.com/remote-jobs.rss"


class WeWorkRemotelyBoard(JobBoard):
    name = "weworkremotely"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        """Fetch WWR RSS feed and filter by keywords."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(WWR_RSS_URL, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    resp.raise_for_status()
                    xml_text = await resp.text()
        except Exception as exc:
            log.error("WeWorkRemotely fetch failed: %s", exc)
            return []

        return self._parse(xml_text, keywords)

    def _parse(self, xml_text: str, keywords: list[str]) -> list[JobListing]:
        """Parse RSS XML into JobListing objects, filtering by keywords."""
        listings: list[JobListing] = []
        kw_lower = [kw.lower() for kw in keywords]

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            log.error("WeWorkRemotely XML parse error: %s", exc)
            return []

        # RSS structure: rss > channel > item
        for item in root.findall(".//item"):
            title_el = item.find("title")
            link_el = item.find("link")
            region_el = item.find("region")

            title = title_el.text or "" if title_el is not None else ""
            url = link_el.text or "" if link_el is not None else ""
            region = region_el.text or "" if region_el is not None else ""

            # WWR titles are "Company: Role" — extract company from title
            if ": " in title:
                company, title = title.split(": ", 1)
            else:
                company = region

            # Filter by keywords
            combined = (title + " " + company).lower()
            if kw_lower and not any(kw in combined for kw in kw_lower):
                continue

            if not url:
                continue

            listings.append(JobListing(
                url=url,
                title=title.strip(),
                company=company.strip(),
                board=self.name,
                location="remote",
                remote="yes",
                raw={"source": "weworkremotely_rss"},
            ))

        log.info("WeWorkRemotely: %d listings after keyword filter", len(listings))
        return listings
