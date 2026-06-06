"""Working Nomads board scraper — public JSON API."""
from __future__ import annotations

import logging

import aiohttp

from .base import JobBoard, JobListing

log = logging.getLogger(__name__)

_API_URL = "https://www.workingnomads.com/api/exposed_jobs/"
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


class WorkingNomadsBoard(JobBoard):
    name = "workingnomads"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        """Fetch Working Nomads API and filter by keywords."""
        headers = {"User-Agent": _USER_AGENT}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    _API_URL,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
        except Exception as exc:
            log.error("WorkingNomads fetch failed: %s", exc)
            return []

        return self._parse(data, keywords)

    def _parse(self, data: list, keywords: list[str]) -> list[JobListing]:
        """Parse Working Nomads JSON array into JobListing objects."""
        if not isinstance(data, list):
            log.warning("WorkingNomads: unexpected API response shape")
            return []

        kw_lower = [kw.lower() for kw in keywords]
        listings: list[JobListing] = []

        for job in data:
            if not isinstance(job, dict):
                continue

            title = job.get("title") or ""
            company = job.get("company_name") or ""
            url = job.get("url") or ""
            location_base = job.get("location_base") or "remote"
            category = job.get("category_name") or ""
            description = job.get("description") or ""

            if not url:
                continue

            # Filter by keywords against title + company + category (tags equivalent)
            combined = (title + " " + company + " " + category).lower()
            if kw_lower and not any(kw in combined for kw in kw_lower):
                continue

            listings.append(JobListing(
                url=url,
                title=title,
                company=company,
                board=self.name,
                location=location_base,
                remote="yes",
                compensation="",
                description=description[:500],
                raw={k: v for k, v in job.items() if k not in ("description",)},
            ))

        log.info("WorkingNomads: %d listings after keyword filter", len(listings))
        return listings
