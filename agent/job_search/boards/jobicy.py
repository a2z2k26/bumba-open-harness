"""Jobicy board scraper — JSON API."""
from __future__ import annotations

import logging

import aiohttp

from .base import JobBoard, JobListing

log = logging.getLogger(__name__)

JOBICY_API_URL = "https://jobicy.com/api/v2/remote-jobs"
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_DEFAULT_COUNT = 50


class JobicyBoard(JobBoard):
    name = "jobicy"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        """Fetch Jobicy API and filter by keywords."""
        headers = {"User-Agent": _USER_AGENT}
        params = {"count": _DEFAULT_COUNT}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    JOBICY_API_URL,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
        except Exception as exc:
            log.error("Jobicy fetch failed: %s", exc)
            return []

        return self._parse(data, keywords)

    def _parse(self, data: dict, keywords: list[str]) -> list[JobListing]:
        """Parse Jobicy JSON response into JobListing objects."""
        if not isinstance(data, dict):
            log.warning("Jobicy: unexpected API response shape")
            return []

        jobs = data.get("jobs") or []
        if not isinstance(jobs, list):
            log.warning("Jobicy: 'jobs' key missing or not a list")
            return []

        kw_lower = [kw.lower() for kw in keywords]
        listings: list[JobListing] = []

        for job in jobs:
            if not isinstance(job, dict):
                continue

            title = job.get("jobTitle") or ""
            company = job.get("companyName") or ""
            url = job.get("url") or ""
            location_str = job.get("jobGeo") or "remote"
            raw_type = job.get("jobType") or ""
            job_type = " ".join(raw_type) if isinstance(raw_type, list) else str(raw_type)
            description = job.get("jobDescription") or ""
            salary_min = job.get("annualSalaryMin")
            salary_max = job.get("annualSalaryMax")

            if not url:
                continue

            # Build compensation string from salary range when available
            compensation = ""
            if salary_min and salary_max:
                compensation = f"${int(salary_min):,} - ${int(salary_max):,}"
            elif salary_min:
                compensation = f"${int(salary_min):,}+"
            elif salary_max:
                compensation = f"up to ${int(salary_max):,}"

            # Filter by keywords against title + company + job type
            combined = (title + " " + company + " " + job_type).lower()
            if kw_lower and not any(kw in combined for kw in kw_lower):
                continue

            listings.append(JobListing(
                url=url,
                title=title,
                company=company,
                board=self.name,
                location=location_str,
                remote="yes",
                compensation=compensation,
                description=description[:500],
                raw={k: v for k, v in job.items() if k not in ("jobDescription",)},
            ))

        log.info("Jobicy: %d listings after keyword filter", len(listings))
        return listings
