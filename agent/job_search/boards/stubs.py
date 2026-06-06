"""Stub implementations for job boards that require auth, paywalls, are defunct, or are AI matching services.

Each class logs a descriptive warning and returns an empty list. These stubs keep the
board registry complete and make it easy to upgrade individual boards later without
touching the registry or orchestrator code.
"""
from __future__ import annotations

import logging

import aiohttp  # noqa: F401 — imported for interface consistency

from .base import JobBoard, JobListing

log = logging.getLogger(__name__)


class IndeedBoard(JobBoard):
    name = "indeed"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        log.warning("IndeedBoard: requires API key or complex anti-scraping bypass. Returning empty list.")
        return []


class LinkedInBoard(JobBoard):
    name = "linkedin"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        log.warning("LinkedInBoard: requires authentication. Returning empty list.")
        return []


class GlassdoorBoard(JobBoard):
    name = "glassdoor"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        log.warning("GlassdoorBoard: requires authentication. Returning empty list.")
        return []


class FlexjobsBoard(JobBoard):
    name = "flexjobs"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        log.warning("FlexjobsBoard: requires paid subscription. Returning empty list.")
        return []


class TheLaddersBoard(JobBoard):
    name = "theladders"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        log.warning("TheLaddersBoard: requires paid subscription. Returning empty list.")
        return []


class OttaBoard(JobBoard):
    name = "otta"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        log.warning("OttaBoard: merged with Welcome to the Jungle, no public API. Returning empty list.")
        return []


class RemoteCoBoard(JobBoard):
    name = "remoteco"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        log.warning("RemoteCoBoard: no public API, HTML scraping not implemented. Returning empty list.")
        return []


class IxdaBoard(JobBoard):
    name = "ixda"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        log.warning("IxdaBoard: no public API, HTML scraping not implemented. Returning empty list.")
        return []


class PangianBoard(JobBoard):
    name = "pangian"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        log.warning("PangianBoard: site appears defunct. Returning empty list.")
        return []


class LetsWorkRemotelyBoard(JobBoard):
    name = "letsworkremotely"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        log.warning("LetsWorkRemotelyBoard: site appears defunct. Returning empty list.")
        return []


class SkipTheDriveBoard(JobBoard):
    name = "skipthedrive"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        log.warning("SkipTheDriveBoard: aggregator, no public API. Returning empty list.")
        return []


class SonaraBoard(JobBoard):
    name = "sonara"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        log.warning("SonaraBoard: AI matching service, not a scrapeable board. Returning empty list.")
        return []


class PathriseBoard(JobBoard):
    name = "pathrise"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        log.warning("PathriseBoard: career service, not a job board. Returning empty list.")
        return []


class TalentpriseBoard(JobBoard):
    name = "talentprise"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        log.warning("TalentpriseBoard: AI matching service, not a scrapeable board. Returning empty list.")
        return []


class PyjamaBoard(JobBoard):
    name = "pyjama"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        log.warning("PyjamaBoard: site status unknown, no public API. Returning empty list.")
        return []


class OpenJobsAIBoard(JobBoard):
    name = "openjobsai"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        log.warning("OpenJobsAIBoard: AI matching service, not a scrapeable board. Returning empty list.")
        return []


class OfferedBoard(JobBoard):
    name = "offered"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        log.warning("OfferedBoard: AI matching service, not a scrapeable board. Returning empty list.")
        return []


class WisefulBoard(JobBoard):
    name = "wiseful"

    async def fetch(self, keywords: list[str], location: str = "remote") -> list[JobListing]:
        log.warning("WisefulBoard: networking platform, not a job board. Returning empty list.")
        return []
