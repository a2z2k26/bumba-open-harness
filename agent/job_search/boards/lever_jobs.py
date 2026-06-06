"""Lever ATS scraper (Sprint 06.07).

Iterates the operator-curated ``lever:`` block in ``config/companies.yaml``
and pulls each company's public job board via the Lever Postings API.
Subclasses ``JobBoard`` so it plugs into the existing
``JobSearchAgent._boards`` list with no other wiring changes.

The endpoint is ``https://api.lever.co/v0/postings/{company}?mode=json``.
Lever's response is a TOP-LEVEL JSON ARRAY of postings (not the
``{"jobs": [...]}`` envelope used by Ashby/Greenhouse) — that is the
key shape difference this module handles.
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

LEVER_API_TEMPLATE = "https://api.lever.co/v0/postings/{company}?mode=json"
COMPANIES_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "companies.yaml"

# Lever does not document a hard rate limit; 1 req/sec is a safety margin
# matching the Ashby/Greenhouse cadence.
RATE_LIMIT_SECONDS: float = 1.0

# Strip simple HTML tags when falling back from descriptionPlain to
# description. Not a full sanitizer — Lever's HTML descriptions are
# well-formed and we only need readable text for the 500-char preview.
_HTML_TAG_RE = re.compile(r"<[^>]+>")


class LeverBoard(JobBoard):
    """Pulls listings from companies hosted on Lever."""

    name = "lever"

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
            log.info("Lever: no companies configured — skipping")
            return []

        kw_lower = [kw.lower() for kw in keywords]
        listings: list[JobListing] = []

        for index, company in enumerate(companies):
            token = company.get("token")
            display_name = company.get("name") or token
            if not token:
                log.warning("Lever: skipping company entry without 'token': %s", company)
                continue

            if index > 0:
                await asyncio.sleep(self._rate_limit_seconds)

            url = LEVER_API_TEMPLATE.format(company=token)
            # NOTE: ``fetch_with_retry`` is type-annotated as
            # ``dict[str, Any] | None``, but at runtime it returns whatever
            # ``aiohttp.ClientResponse.json()`` parses — for Lever that's a
            # top-level list. The hint is misleading; the runtime is
            # permissive. We re-validate via ``isinstance(data, list)`` in
            # ``_parse``.
            data = await fetch_with_retry(url)
            if data is None:
                log.info("Lever: %s (%s) returned no data", display_name, token)
                continue

            listings.extend(self._parse(data, display_name, kw_lower))

        log.info("Lever: %d listings after keyword filter", len(listings))
        return listings

    def _load_companies(self) -> list[dict[str, Any]]:
        if not self._companies_config_path.exists():
            log.info(
                "Lever: companies config not found at %s — skipping",
                self._companies_config_path,
            )
            return []
        try:
            data = yaml.safe_load(self._companies_config_path.read_text()) or {}
        except yaml.YAMLError as exc:
            log.error("Lever: companies.yaml parse failed: %s", exc)
            return []
        block = data.get("lever") or []
        if not isinstance(block, list):
            log.warning("Lever: companies.yaml 'lever' block is not a list")
            return []
        return [item for item in block if isinstance(item, dict)]

    def _parse(
        self,
        data: Any,
        company_display_name: str,
        kw_lower: list[str],
    ) -> list[JobListing]:
        # Lever returns a TOP-LEVEL ARRAY, unlike Ashby/Greenhouse which
        # wrap their postings in an object.
        if not isinstance(data, list):
            return []

        out: list[JobListing] = []
        for job in data:
            if not isinstance(job, dict):
                continue
            url = job.get("hostedUrl") or job.get("applyUrl") or ""
            title = job.get("text") or ""
            if not url or not title:
                continue

            categories = job.get("categories") or {}
            if not isinstance(categories, dict):
                categories = {}
            location_str = categories.get("location") or ""
            if not isinstance(location_str, str):
                location_str = ""

            workplace = job.get("workplaceType") or ""
            if not isinstance(workplace, str):
                workplace = ""
            remote_str = (
                "yes"
                if "remote" in workplace.lower() or "remote" in location_str.lower()
                else ""
            )

            description = self._extract_description(job)
            compensation = self._format_compensation(job.get("salaryRange"))
            company = job.get("company") or company_display_name

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
                    raw={
                        k: v
                        for k, v in job.items()
                        if k not in ("description", "descriptionHtml", "descriptionPlain")
                    },
                )
            )
        return out

    @staticmethod
    def _extract_description(job: dict[str, Any]) -> str:
        plain = job.get("descriptionPlain")
        if isinstance(plain, str) and plain.strip():
            return plain
        html = job.get("description")
        if isinstance(html, str) and html.strip():
            return _HTML_TAG_RE.sub("", html).strip()
        return ""

    @staticmethod
    def _format_compensation(salary: Any) -> str:
        if not isinstance(salary, dict):
            return ""
        lo = salary.get("min")
        hi = salary.get("max")
        currency = salary.get("currency") or ""
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
            lo_fmt = f"${int(lo):,}"
            hi_fmt = f"${int(hi):,}"
            if currency:
                return f"{lo_fmt} - {hi_fmt} {currency}".strip()
            return f"{lo_fmt} - {hi_fmt}".strip()
        return ""
