"""Greenhouse ATS scraper (Sprint 06.06).

Iterates the operator-curated ``greenhouse:`` block in
``config/companies.yaml`` and pulls each company's public job board via
the Greenhouse Job Board API. Subclasses ``JobBoard`` so it plugs into
the existing ``JobSearchAgent._boards`` list with no other wiring
changes.

The endpoint is ``https://boards-api.greenhouse.io/v1/boards/{token}/jobs``.
``content=true`` asks Greenhouse to inline the HTML job description so
the scraper does not need a follow-up call per listing.
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

import yaml

from ._ats_api import fetch_with_retry
from .base import JobBoard, JobListing

log = logging.getLogger(__name__)

GREENHOUSE_API_TEMPLATE = (
    "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
)
COMPANIES_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "companies.yaml"

# Greenhouse is more permissive than Ashby, but we keep the same 1 req/sec
# safety margin for parity with the Ashby scraper (Sprint 06.05).
RATE_LIMIT_SECONDS: float = 1.0

# Defensive HTML strip — Greenhouse's ``content`` field is HTML. Full-on
# HTML parsing would be overkill for the description preview we keep, so a
# regex tag-strip is sufficient here.
_HTML_TAG_RE = re.compile(r"<[^>]+>")


class GreenhouseBoard(JobBoard):
    """Pulls listings from companies hosted on Greenhouse."""

    name = "greenhouse"

    def __init__(
        self,
        *,
        companies_config_path: Path | None = None,
        rate_limit_seconds: float = RATE_LIMIT_SECONDS,
    ) -> None:
        self._companies_config_path = companies_config_path or COMPANIES_CONFIG_PATH
        self._rate_limit_seconds = rate_limit_seconds

    async def fetch(
        self,
        keywords: list[str],
        location: str = "remote",
    ) -> list[JobListing]:
        companies = self._load_companies()
        if not companies:
            log.info("Greenhouse: no companies configured — skipping")
            return []

        kw_lower = [kw.lower() for kw in keywords]
        listings: list[JobListing] = []

        for index, company in enumerate(companies):
            token = company.get("token")
            display_name = company.get("name") or token
            if not token:
                log.warning(
                    "Greenhouse: skipping company entry without 'token': %s",
                    company,
                )
                continue

            if index > 0:
                await asyncio.sleep(self._rate_limit_seconds)

            url = GREENHOUSE_API_TEMPLATE.format(token=token)
            data = await fetch_with_retry(url)
            if data is None:
                log.info("Greenhouse: %s (%s) returned no data", display_name, token)
                continue

            listings.extend(self._parse(data, display_name, kw_lower))

        log.info("Greenhouse: %d listings after keyword filter", len(listings))
        return listings

    def _load_companies(self) -> list[dict[str, Any]]:
        if not self._companies_config_path.exists():
            log.info(
                "Greenhouse: companies config not found at %s — skipping",
                self._companies_config_path,
            )
            return []
        try:
            data = yaml.safe_load(self._companies_config_path.read_text()) or {}
        except yaml.YAMLError as exc:
            log.error("Greenhouse: companies.yaml parse failed: %s", exc)
            return []
        block = data.get("greenhouse") or []
        if not isinstance(block, list):
            log.warning("Greenhouse: companies.yaml 'greenhouse' block is not a list")
            return []
        return [item for item in block if isinstance(item, dict)]

    def _parse(
        self,
        data: dict[str, Any],
        company_display_name: str,
        kw_lower: list[str],
    ) -> list[JobListing]:
        if not isinstance(data, dict):
            return []
        jobs = data.get("jobs") or []
        if not isinstance(jobs, list):
            return []

        out: list[JobListing] = []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            url = job.get("absolute_url") or ""
            title = job.get("title") or ""
            if not url or not title:
                continue

            location_str = self._location_name(job.get("location"))
            remote_str = "yes" if "remote" in location_str.lower() else ""
            description = self._strip_html(job.get("content") or "")

            company_block = job.get("company")
            if isinstance(company_block, dict):
                company = company_block.get("name") or company_display_name
            else:
                company = company_display_name

            if kw_lower:
                blob = (title + " " + company + " " + description[:300]).lower()
                if not any(kw in blob for kw in kw_lower):
                    continue

            out.append(
                JobListing(
                    url=url,
                    title=title,
                    company=company,
                    board=self.name,
                    location=location_str,
                    remote=remote_str,
                    # Greenhouse rarely publishes structured comp on the public
                    # Job Board API — leave empty rather than fabricate a value.
                    compensation="",
                    description=description[:500],
                    raw={k: v for k, v in job.items() if k != "content"},
                )
            )
        return out

    @staticmethod
    def _location_name(loc: Any) -> str:
        if isinstance(loc, dict):
            return loc.get("name") or ""
        if isinstance(loc, str):
            return loc
        return ""

    @staticmethod
    def _strip_html(content: str) -> str:
        if not content:
            return ""
        # Defensive — full HTML parsing is overkill for a preview blob.
        return _HTML_TAG_RE.sub("", content).strip()
