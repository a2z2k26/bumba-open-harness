"""Y Combinator / Work at a Startup board scraper — embedded JSON extraction."""
from __future__ import annotations

import html as html_mod
import json
import logging
import re

import aiohttp

from .base import JobBoard, JobListing

log = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Map common search keywords to WaaS category page slugs.
_CATEGORY_SLUGS: dict[str, str] = {
    "design": "designer",
    "designer": "designer",
    "product design": "designer",
    "ux": "designer",
    "ui": "designer",
    "engineer": "software-engineer",
    "software": "software-engineer",
    "developer": "software-engineer",
    "product": "product-manager",
    "product manager": "product-manager",
    "marketing": "marketing",
    "sales": "sales-manager",
    "operations": "operations",
    "finance": "finance",
    "legal": "legal",
    "recruiting": "recruiting",
    "science": "science",
}


class YCombinatorBoard(JobBoard):
    name = "ycombinator"

    # ── public API ──────────────────────────────────────────────

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        """Fetch YC Work at a Startup listings.

        The site embeds structured job data as JSON inside a ``data-page``
        attribute on the React mount-point div.  We fetch one or more
        category pages, extract the JSON, and parse the jobs array.
        """
        urls = self._build_urls(keywords)
        all_listings: list[JobListing] = []
        seen_ids: set[int] = set()
        headers = {"User-Agent": _USER_AGENT}

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                for url in urls:
                    try:
                        async with session.get(
                            url,
                            timeout=aiohttp.ClientTimeout(total=30),
                            allow_redirects=True,
                        ) as resp:
                            if resp.status != 200:
                                log.warning("YCombinator %s returned %d", url, resp.status)
                                continue
                            page_html = await resp.text()
                    except Exception as exc:
                        log.warning("YCombinator fetch %s failed: %s", url, exc)
                        continue

                    jobs = self._extract_jobs_json(page_html)
                    for job in jobs:
                        job_id = job.get("id", 0)
                        if job_id and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            listing = self._job_to_listing(job, keywords)
                            if listing:
                                all_listings.append(listing)

        except Exception as exc:
            log.error("YCombinator session failed: %s", exc)
            return []

        log.info(
            "YCombinator: %d listings from %d pages after keyword filter",
            len(all_listings),
            len(urls),
        )
        return all_listings

    # ── URL helpers ─────────────────────────────────────────────

    def _build_urls(self, keywords: list[str]) -> list[str]:
        """Map keywords to WaaS category page URLs."""
        urls: list[str] = []
        used_slugs: set[str] = set()

        for kw in keywords:
            slug = _CATEGORY_SLUGS.get(kw.lower())
            if slug and slug not in used_slugs:
                used_slugs.add(slug)
                urls.append(f"https://www.workatastartup.com/jobs/l/{slug}")

        # Always include the main jobs page as a fallback / extra source.
        if not urls:
            urls.append("https://www.workatastartup.com/jobs")

        return urls

    # ── JSON extraction from HTML ──────────────────────────────

    @staticmethod
    def _extract_jobs_json(page_html: str) -> list[dict]:
        """Pull the jobs array out of the React ``data-page`` prop."""
        m = re.search(r'data-page="([^"]+)"', page_html)
        if not m:
            log.debug("YCombinator: no data-page attribute found")
            return []

        try:
            raw = html_mod.unescape(m.group(1))
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("YCombinator: data-page JSON parse failed: %s", exc)
            return []

        props = data.get("props", {})
        jobs = props.get("jobs", [])
        if not isinstance(jobs, list):
            return []
        return jobs

    # ── Single-job converter ────────────────────────────────────

    def _job_to_listing(self, job: dict, keywords: list[str]) -> JobListing | None:
        """Convert a single embedded job dict to a JobListing, or None."""
        title = job.get("title", "")
        company = job.get("companyName", "")
        company_slug = job.get("companySlug", "")
        job_location = job.get("location", "Remote")
        role_type = job.get("roleType", "")
        job_type = job.get("jobType", "")
        tagline = job.get("companyOneLiner", "")
        job_id = job.get("id", 0)

        if not title or not company:
            return None

        # Build a usable job URL — the company page on WaaS
        url = (
            f"https://www.workatastartup.com/companies/{company_slug}"
            if company_slug
            else ""
        )
        if not url:
            return None

        # Keyword filtering — match against title + company + role type
        kw_lower = [kw.lower() for kw in keywords]
        combined = (title + " " + company + " " + role_type).lower()
        if kw_lower and not any(kw in combined for kw in kw_lower):
            return None

        description = f"{tagline}. {role_type}" if tagline else role_type

        return JobListing(
            url=url,
            title=title,
            company=company,
            board=self.name,
            location=job_location or "Remote",
            remote="yes" if not job_location or "remote" in job_location.lower() else "",
            compensation="",
            description=description[:500],
            raw={
                "source": "ycombinator_json",
                "company_slug": company_slug,
                "job_id": str(job_id),
                "job_type": job_type,
            },
        )

    # ── Legacy Algolia JSON parser (kept for backward compat + tests) ──

    def _parse(self, data: dict, keywords: list[str]) -> list[JobListing]:
        """Parse Algolia JSON response.  Kept for existing test compatibility."""
        kw_lower = [kw.lower() for kw in keywords]
        listings: list[JobListing] = []

        results = data.get("results", [])
        if not results:
            return []

        hits = results[0].get("hits", [])

        for hit in hits:
            title = hit.get("title", "")
            company = hit.get("companyName", "")
            slug = hit.get("slug", "")
            company_slug = hit.get("companySlug", "")
            job_location = hit.get("location", "Remote")
            salary_min = hit.get("salaryMin")
            salary_max = hit.get("salaryMax")
            description = hit.get("description", "")

            url = f"https://www.workatastartup.com/jobs/{slug}" if slug else ""
            if not url:
                continue

            compensation = ""
            if salary_min and salary_max:
                compensation = f"${salary_min:,} - ${salary_max:,}"
            elif salary_min:
                compensation = f"${salary_min:,}+"

            combined = (title + " " + company).lower()
            if kw_lower and not any(kw in combined for kw in kw_lower):
                continue

            listings.append(JobListing(
                url=url,
                title=title,
                company=company,
                board=self.name,
                location=job_location,
                remote="yes",
                compensation=compensation,
                description=description[:500],
                raw={"source": "ycombinator_algolia", "company_slug": company_slug},
            ))

        log.info("YCombinator: %d listings after keyword filter", len(listings))
        return listings
