"""Remote OK board scraper — JSON API."""
from __future__ import annotations

import logging

import aiohttp

from .base import JobBoard, JobListing

log = logging.getLogger(__name__)

REMOTEOK_API_URL = "https://remoteok.com/api"
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


class RemoteOKBoard(JobBoard):
    name = "remoteok"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        """Fetch Remote OK API and filter by keywords."""
        headers = {"User-Agent": _USER_AGENT}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    REMOTEOK_API_URL,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
        except Exception as exc:
            log.error("RemoteOK fetch failed: %s", exc)
            return []

        return self._parse(data, keywords)

    def _parse(self, data: list, keywords: list[str]) -> list[JobListing]:
        """Parse Remote OK JSON array into JobListing objects.

        The first element of the array is metadata — skip it.
        """
        if not isinstance(data, list) or len(data) < 2:
            log.warning("RemoteOK: unexpected API response shape")
            return []

        kw_lower = [kw.lower() for kw in keywords]
        listings: list[JobListing] = []

        # Skip index 0 (metadata element)
        for job in data[1:]:
            if not isinstance(job, dict):
                continue

            title = job.get("position") or job.get("title") or ""
            company = job.get("company") or ""
            url = job.get("url") or ""
            tags = job.get("tags") or []
            description = job.get("description") or ""
            salary_min = job.get("salary_min")
            salary_max = job.get("salary_max")

            compensation = ""
            if salary_min and salary_max:
                compensation = f"${salary_min:,} - ${salary_max:,}"
            elif salary_min:
                compensation = f"${salary_min:,}+"

            # Build canonical URL from slug if needed
            if not url:
                slug = job.get("slug") or ""
                if slug:
                    url = f"https://remoteok.com/remote-jobs/{slug}"

            if not url:
                continue

            # Filter by keywords against title + tags + company
            tag_text = " ".join(str(t) for t in tags)
            combined = (title + " " + company + " " + tag_text).lower()
            if kw_lower and not any(kw in combined for kw in kw_lower):
                continue

            listings.append(JobListing(
                url=url,
                title=title,
                company=company,
                board=self.name,
                location="remote",
                remote="yes",
                compensation=compensation,
                description=description[:500],  # truncate for storage
                raw={k: v for k, v in job.items() if k not in ("description",)},
            ))

        log.info("RemoteOK: %d listings after keyword filter", len(listings))
        return listings
