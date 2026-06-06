"""Nodesk remote design jobs scraper — RSS feed extraction.

Nodesk uses Algolia for client-side rendering, so the HTML page contains no
scrapeable job links.  However, Nodesk provides an RSS feed at
``/remote-jobs/design/index.xml`` which contains recent job listings with
titles in the format "Title at Company" and description text.

Each RSS ``<item>`` contains:
  - ``<title>Title at Company</title>``
  - ``<link>https://nodesk.co/remote-jobs/SLUG/</link>``
  - ``<description>Company is hiring a remote Title...</description>``
  - ``<pubDate>...</pubDate>``
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

import aiohttp

from .base import JobBoard, JobListing

log = logging.getLogger(__name__)

_BASE_URL = "https://nodesk.co"
_RSS_URL = "https://nodesk.co/remote-jobs/design/index.xml"
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Parse "Title at Company" pattern from RSS titles
_TITLE_AT_COMPANY_RE = re.compile(r'^(.+?)\s+at\s+(.+)$')


class NodeskBoard(JobBoard):
    name = "nodesk"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        """Fetch and parse Nodesk RSS feed for remote design jobs."""
        headers = {"User-Agent": _USER_AGENT}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    _RSS_URL,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    resp.raise_for_status()
                    xml_text = await resp.text()
        except Exception as exc:
            log.error("Nodesk fetch failed: %s", exc)
            return []

        return self._parse(xml_text, keywords, location)

    def _parse(self, xml_text: str, keywords: list[str], location: str = "remote") -> list[JobListing]:
        """Parse RSS XML and extract job listings."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            log.warning("Nodesk: RSS XML parse error: %s", exc)
            return []

        channel = root.find("channel")
        if channel is None:
            log.warning("Nodesk: no <channel> element in RSS")
            return []

        kw_lower = [kw.lower() for kw in keywords]
        seen_urls: set[str] = set()
        listings: list[JobListing] = []

        for item in channel.findall("item"):
            raw_title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            description = (item.findtext("description") or "").strip()

            if not raw_title or not link:
                continue

            if link in seen_urls:
                continue
            seen_urls.add(link)

            # Parse "Title at Company" format
            m = _TITLE_AT_COMPANY_RE.match(raw_title)
            if m:
                title = m.group(1).strip()
                company = m.group(2).strip()
            else:
                title = raw_title
                company = ""

            # Keyword filter
            combined = (title + " " + company + " " + description[:200]).lower()
            if kw_lower and not any(kw in combined for kw in kw_lower):
                continue

            listings.append(JobListing(
                url=link,
                title=title,
                company=company,
                board=self.name,
                location=location,
                remote="yes",
                compensation="",
                description=description[:500],
                raw={"rss_title": raw_title},
            ))

        log.info("Nodesk: %d listings after keyword filter", len(listings))
        return listings
