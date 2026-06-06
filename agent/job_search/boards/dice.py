"""Dice job board scraper — HTML page with embedded Next.js JSON data.

The old DHI Group JSON API (job-search-api.svc.dhigroupinc.com) returns 403
as of early 2025.  The public search page at dice.com/jobs still works and
embeds job data as JSON inside Next.js RSC (React Server Components) streaming
payloads.  We fetch the HTML, extract the embedded ``jobList.data`` array, and
feed it to ``_parse()`` which keeps the same interface as before.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import quote_plus

import aiohttp

from .base import JobBoard, JobListing

log = logging.getLogger(__name__)

_DICE_SEARCH_URL = "https://www.dice.com/jobs"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _extract_jobs_from_html(html: str) -> dict:
    """Pull the ``jobList`` JSON out of the Next.js RSC stream.

    Dice renders its search page via React Server Components.  The job data
    is embedded inside ``self.__next_f.push([...])`` calls as an escaped JSON
    string where inner double-quotes appear as ``\\\\"`` (literal backslash +
    double-quote).

    We unescape the whole page, locate the ``"jobList":{"data":[...]}``
    fragment, and return a dict shaped like ``{"data": [<job objects>]}``.
    This keeps ``_parse()`` backward-compatible with the old API shape.
    """
    # Unescape the RSC string encoding: \\" -> "
    unescaped = html.replace('\\"', '"')

    marker = '"jobList":{"data":'
    idx = unescaped.find(marker)
    if idx == -1:
        log.warning("Dice: jobList marker not found in HTML")
        return {}

    arr_start = idx + len(marker)
    arr_text = _extract_json_array(unescaped, arr_start)
    if arr_text is None:
        log.warning("Dice: failed to extract JSON array from HTML")
        return {}

    try:
        jobs = json.loads(arr_text)
    except json.JSONDecodeError as exc:
        log.warning("Dice: JSON decode error: %s", exc)
        return {}

    return {"data": jobs}


def _extract_json_array(text: str, start: int) -> str | None:
    """Return the substring of *text* forming a balanced JSON array.

    Uses bracket counting with proper string/escape handling so nested
    objects and arrays are included.
    """
    if start >= len(text) or text[start] != "[":
        return None

    depth = 0
    in_string = False
    escape = False
    limit = min(start + 500_000, len(text))

    for i in range(start, limit):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


class DiceBoard(JobBoard):
    name = "dice"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        """Fetch Dice search page and return keyword-matched listings."""
        # Use first keyword only — joining all keywords into one query produces
        # garbage results from Dice's search engine.
        q = keywords[0] if keywords else "designer"
        is_remote = location.lower() in ("remote", "")

        params: dict[str, str] = {
            "q": q,
            "countryCode": "US",
            "radius": "30",
            "radiusUnit": "mi",
            "page": "1",
            "pageSize": "20",
            "language": "en",
        }
        if is_remote:
            params["filters.isRemote"] = "true"

        query_string = "&".join(
            f"{k}={quote_plus(v)}" for k, v in params.items()
        )
        url = f"{_DICE_SEARCH_URL}?{query_string}"

        try:
            async with aiohttp.ClientSession(headers=_HEADERS) as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    resp.raise_for_status()
                    html = await resp.text()
        except Exception as exc:
            log.error("Dice fetch failed: %s", exc)
            return []

        data = _extract_jobs_from_html(html)
        if not data:
            log.warning("Dice: no job data extracted from HTML")
            return []

        return self._parse(data, keywords)

    def _parse(self, data: dict, keywords: list[str]) -> list[JobListing]:
        """Parse Dice job data into JobListing objects.

        Expected shape (unchanged from old API)::

            {
                "data": [
                    {
                        "title": str,
                        "companyName": str,
                        "detailsPageUrl": str,
                        "jobLocation": {"displayName": str, ...},
                        "salary": str | null,
                        ...
                    },
                    ...
                ]
            }
        """
        if not isinstance(data, dict):
            log.warning("Dice: unexpected top-level response type: %s", type(data).__name__)
            return []

        jobs = data.get("data")
        if not isinstance(jobs, list):
            log.warning("Dice: 'data' key missing or not a list")
            return []

        kw_lower = [kw.lower() for kw in keywords]
        listings: list[JobListing] = []

        for job in jobs:
            if not isinstance(job, dict):
                continue

            title = job.get("title") or ""
            company = job.get("companyName") or ""
            url = job.get("detailsPageUrl") or ""
            if url and not url.startswith("http"):
                url = f"https://www.dice.com{url}"

            # Location lives in a nested object.
            job_location = job.get("jobLocation") or {}
            location_str = (
                job_location.get("displayName") or ""
                if isinstance(job_location, dict)
                else str(job_location)
            )

            salary = job.get("salary") or ""
            compensation = str(salary).strip() if salary else ""

            if not url:
                continue

            # Keyword filter against title + company
            combined = (title + " " + company).lower()
            if kw_lower and not any(kw in combined for kw in kw_lower):
                continue

            listings.append(JobListing(
                url=url,
                title=title,
                company=company,
                board=self.name,
                location=location_str or "remote",
                remote="yes",
                compensation=compensation,
                description="",
                raw={k: v for k, v in job.items()},
            ))

        log.info("Dice: %d listings after keyword filter", len(listings))
        return listings
