"""Remotive board scraper — JSON API."""
from __future__ import annotations

import logging

import aiohttp

from .base import JobBoard, JobListing

log = logging.getLogger(__name__)

REMOTIVE_API_URL = "https://remotive.com/api/remote-jobs"
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


class RemotiveBoard(JobBoard):
    name = "remotive"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        """Fetch Remotive API and filter by keywords."""
        headers = {"User-Agent": _USER_AGENT}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    REMOTIVE_API_URL,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
        except Exception as exc:
            log.error("Remotive fetch failed: %s", exc)
            return []

        return self._parse(data, keywords)

    def _parse(self, data: dict, keywords: list[str]) -> list[JobListing]:
        """Parse Remotive JSON response into JobListing objects."""
        if not isinstance(data, dict):
            log.warning("Remotive: unexpected API response shape")
            return []

        jobs = data.get("jobs") or []
        if not isinstance(jobs, list):
            log.warning("Remotive: 'jobs' key missing or not a list")
            return []

        kw_lower = [kw.lower() for kw in keywords]
        listings: list[JobListing] = []

        for job in jobs:
            if not isinstance(job, dict):
                continue

            title = job.get("title") or ""
            company = job.get("company_name") or ""
            url = job.get("url") or ""
            location_str = job.get("candidate_required_location") or "remote"
            salary = job.get("salary") or ""
            description = job.get("description") or ""
            tags = job.get("tags") or []

            if not url:
                continue

            # Filter by keywords against title + company + tags
            tag_text = " ".join(str(t) for t in tags)
            combined = (title + " " + company + " " + tag_text).lower()
            if kw_lower and not any(kw in combined for kw in kw_lower):
                continue

            listings.append(JobListing(
                url=url,
                title=title,
                company=company,
                board=self.name,
                location=location_str,
                remote="yes",
                compensation=salary,
                description=description[:500],
                raw={k: v for k, v in job.items() if k not in ("description",)},
            ))

        log.info("Remotive: %d listings after keyword filter", len(listings))
        return listings
