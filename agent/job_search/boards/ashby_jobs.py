"""Ashby ATS scraper (Sprint 06.05).

Iterates the operator-curated ``ashby:`` block in ``config/companies.yaml``
and pulls each company's public job board via the Ashby Posting API.
Subclasses ``JobBoard`` so it plugs into the existing
``JobSearchAgent._boards`` list with no other wiring changes.

The endpoint is ``https://api.ashbyhq.com/posting-api/job-board/{token}``.
``includeCompensation=true`` adds the structured ``compensation`` block
when the company elected to publish it; absence is normal.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import yaml

from ._ats_api import fetch_with_retry
from .base import JobBoard, JobListing

log = logging.getLogger(__name__)

ASHBY_API_TEMPLATE = "https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"
COMPANIES_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "companies.yaml"

# Ashby documents 1 req/sec per company token; keep a small safety margin.
RATE_LIMIT_SECONDS: float = 1.0


class AshbyJobsBoard(JobBoard):
    """Pulls listings from companies hosted on Ashby."""

    name = "ashby"

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
            log.info("Ashby: no companies configured — skipping")
            return []

        kw_lower = [kw.lower() for kw in keywords]
        listings: list[JobListing] = []

        for index, company in enumerate(companies):
            token = company.get("token")
            display_name = company.get("name") or token
            if not token:
                log.warning("Ashby: skipping company entry without 'token': %s", company)
                continue

            if index > 0:
                await asyncio.sleep(self._rate_limit_seconds)

            url = ASHBY_API_TEMPLATE.format(token=token)
            data = await fetch_with_retry(url)
            if data is None:
                log.info("Ashby: %s (%s) returned no data", display_name, token)
                continue

            listings.extend(self._parse(data, display_name, kw_lower))

        log.info("Ashby: %d listings after keyword filter", len(listings))
        return listings

    def _load_companies(self) -> list[dict[str, Any]]:
        if not self._companies_config_path.exists():
            log.info(
                "Ashby: companies config not found at %s — skipping",
                self._companies_config_path,
            )
            return []
        try:
            data = yaml.safe_load(self._companies_config_path.read_text()) or {}
        except yaml.YAMLError as exc:
            log.error("Ashby: companies.yaml parse failed: %s", exc)
            return []
        block = data.get("ashby") or []
        if not isinstance(block, list):
            log.warning("Ashby: companies.yaml 'ashby' block is not a list")
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
            url = job.get("jobUrl") or job.get("applyUrl") or ""
            title = job.get("title") or ""
            if not url or not title:
                continue

            location_str = job.get("locationName") or ""
            workplace = job.get("workplaceType") or ""
            remote_str = "yes" if "remote" in workplace.lower() or "remote" in location_str.lower() else ""
            description = job.get("descriptionPlain") or ""
            compensation = self._format_compensation(job.get("compensation"))

            company = job.get("companyName") or company_display_name

            if kw_lower:
                blob = (title + " " + company + " " + (description[:300] if description else "")).lower()
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
                    compensation=compensation,
                    description=description[:500],
                    raw={k: v for k, v in job.items() if k not in ("descriptionPlain", "descriptionHtml")},
                )
            )
        return out

    @staticmethod
    def _format_compensation(comp: Any) -> str:
        if not isinstance(comp, dict):
            return ""
        summary = comp.get("compensationTierSummary")
        if isinstance(summary, str) and summary:
            return summary
        tiers = comp.get("compensationTiers") or []
        if isinstance(tiers, list) and tiers:
            first = tiers[0]
            if isinstance(first, dict):
                return first.get("tierSummary") or ""
        return ""
