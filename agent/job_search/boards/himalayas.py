"""Himalayas board scraper — JSON API."""
from __future__ import annotations

import asyncio
import logging

import aiohttp

from .base import JobBoard, JobListing

log = logging.getLogger(__name__)

HIMALAYAS_API_URL = "https://himalayas.app/jobs/api"
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_PAGE_LIMIT = 20          # API max per request
_MAX_PAGES = 25           # Scan up to 500 recent jobs (25 pages x 20)
_TARGET_MATCHES = 15      # Stop early once we have enough matches
_PAGE_DELAY = 0.3         # Seconds between requests to avoid rate-limiting


class HimalayasBoard(JobBoard):
    name = "himalayas"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        """Fetch Himalayas API with pagination and filter by keywords."""
        headers = {"User-Agent": _USER_AGENT}
        all_listings: list[JobListing] = []

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                for page in range(_MAX_PAGES):
                    params = {"limit": _PAGE_LIMIT, "offset": page * _PAGE_LIMIT}
                    try:
                        async with session.get(
                            HIMALAYAS_API_URL,
                            params=params,
                            timeout=aiohttp.ClientTimeout(total=30),
                        ) as resp:
                            resp.raise_for_status()
                            data = await resp.json(content_type=None)
                    except Exception as exc:
                        log.warning("Himalayas page %d failed: %s", page, exc)
                        break

                    page_listings = self._parse(data, keywords)
                    all_listings.extend(page_listings)

                    # Stop early if we have enough matches
                    if len(all_listings) >= _TARGET_MATCHES:
                        log.info("Himalayas: reached %d matches, stopping pagination", len(all_listings))
                        break

                    # Check if there are more pages
                    if isinstance(data, dict):
                        total = data.get("totalCount", 0)
                        if (page + 1) * _PAGE_LIMIT >= total:
                            break

                    # Rate-limit courtesy delay between pages
                    if page < _MAX_PAGES - 1:
                        await asyncio.sleep(_PAGE_DELAY)

        except Exception as exc:
            log.error("Himalayas fetch failed: %s", exc)
            return []

        log.info("Himalayas: %d total listings after pagination", len(all_listings))
        return all_listings

    def _parse(self, data: list | dict, keywords: list[str]) -> list[JobListing]:
        """Parse Himalayas JSON response into JobListing objects."""
        # API may return a bare list or a dict with a jobs key
        if isinstance(data, dict):
            jobs = data.get("jobs") or []
        elif isinstance(data, list):
            jobs = data
        else:
            log.warning("Himalayas: unexpected API response shape")
            return []

        kw_lower = [kw.lower() for kw in keywords]
        listings: list[JobListing] = []

        for job in jobs:
            if not isinstance(job, dict):
                continue

            title = job.get("title") or ""
            company = job.get("companyName") or ""
            # API returns applicationLink; fall back to url for test compat
            url = job.get("applicationLink") or job.get("url") or ""
            location_restrictions = job.get("locationRestrictions") or []
            description = job.get("description") or ""
            excerpt = job.get("excerpt") or ""
            categories = job.get("categories") or []
            parent_categories = job.get("parentCategories") or []
            # Salary: API uses minSalary/maxSalary; fall back to salaryMin/salaryMax
            salary = job.get("salary") or ""
            if not salary:
                salary_min = job.get("minSalary") or job.get("salaryMin")
                salary_max = job.get("maxSalary") or job.get("salaryMax")
                currency = job.get("currency") or job.get("salaryCurrency") or "USD"
                if salary_min and salary_max:
                    salary = f"{currency} {salary_min:,} - {salary_max:,}"
                elif salary_min:
                    salary = f"{currency} {salary_min:,}+"

            # Build URL from guid/slug if the url field is absent or relative
            if url and not url.startswith("http"):
                url = f"https://himalayas.app{url}"
            if not url:
                slug = job.get("guid") or job.get("slug") or ""
                if slug:
                    url = f"https://himalayas.app/jobs/{slug}"

            if not url:
                continue

            # Normalise location to a readable string
            if isinstance(location_restrictions, list):
                location_str = ", ".join(str(r) for r in location_restrictions) or "remote"
            else:
                location_str = str(location_restrictions) or "remote"

            # Filter by keywords using a tiered approach:
            #   - Single-word keywords match against title + company +
            #     categories + parentCategories + excerpt (NOT full
            #     description, which is HTML and almost always contains
            #     common words like "design", "product", etc.)
            #   - Multi-word keywords (e.g. "product designer") also
            #     match against the full description — these are specific
            #     enough to avoid false positives.
            cat_text = " ".join(str(c) for c in categories)
            pcat_text = " ".join(str(c) for c in parent_categories)
            primary = " ".join([
                title, company, cat_text, pcat_text, excerpt,
            ]).lower()

            if kw_lower:
                matched = False
                for kw in kw_lower:
                    if kw in primary:
                        matched = True
                        break
                    # Multi-word keywords can also match description
                    if " " in kw and kw in description.lower():
                        matched = True
                        break
                if not matched:
                    continue

            listings.append(JobListing(
                url=url,
                title=title,
                company=company,
                board=self.name,
                location=location_str,
                remote="yes",
                compensation=str(salary) if salary else "",
                description=(excerpt or description)[:500],
                raw={k: v for k, v in job.items() if k not in ("description",)},
            ))

        log.info("Himalayas: %d listings after keyword filter", len(listings))
        return listings
