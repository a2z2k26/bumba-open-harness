"""Z4 Tool: scrape_boards — canonical implementation.

This module IS the canonical implementation of ``scrape_boards``. The
chief-side wrapper at ``teams/tools/_job_search.py::scrape_boards``
imports from here (``from job_search.tools.boards import scrape_boards
as _scrape``) and adapts the call to ``RunContext[BridgeDeps]`` for the
Pydantic AI tool surface.

Sprint HI-15 (#1882) — the prior docstring claimed the inverse. Audit
HI-15 of the 2026-05-12 comprehensive audit caught the lie; this is
the correction.
"""
from __future__ import annotations

import asyncio
import logging

from pydantic_ai import RunContext

from job_search.boards.ashby_jobs import AshbyJobsBoard
from job_search.boards.behance import BehanceBoard
from job_search.boards.builtin import BuiltInBoard
from job_search.boards.coroflot import CoroflotBoard
from job_search.boards.dice import DiceBoard
from job_search.boards.dribbble import DribbbleBoard
from job_search.boards.greenhouse_jobs import GreenhouseBoard
from job_search.boards.himalayas import HimalayasBoard
from job_search.boards.jobicy import JobicyBoard
from job_search.boards.lever_jobs import LeverBoard
from job_search.boards.nodesk import NodeskBoard
from job_search.boards.remoteok import RemoteOKBoard
from job_search.boards.remotive import RemotiveBoard
from job_search.boards.weworkremotely import WeWorkRemotelyBoard
from job_search.boards.workingnomads import WorkingNomadsBoard
from job_search.boards.yc_workatastartup import YCombinatorBoard
from job_search.criteria import SearchCriteria
from job_search.models import JobListing, ScrapeResult

log = logging.getLogger(__name__)

# All boards, in order of expected yield. Mirrors the canonical roster in
# ``JobSearchAgent._boards`` (agent.py) — 16 working boards: 7 Tier 1 public
# APIs, 3 Tier 1b ATS direct-API boards (Ashby/Greenhouse/Lever), 6 Tier 2
# HTML scrapers. Stubs (Wellfound/AIGA/AuthenticJobs) were removed in
# Sprint P4.5 (#1731) per operator-greenlit Option B (union to 16).
_BOARD_CLASSES = [
    # Tier 1: Public APIs
    RemotiveBoard,
    RemoteOKBoard,
    WeWorkRemotelyBoard,
    HimalayasBoard,
    JobicyBoard,
    NodeskBoard,
    WorkingNomadsBoard,
    BuiltInBoard,
    # Tier 1b: ATS direct APIs (operator-curated company seeds in
    # config/companies.yaml; empty seed list means graceful no-op)
    AshbyJobsBoard,
    GreenhouseBoard,
    LeverBoard,
    # Tier 2: HTML scrapers (design-specific)
    DribbbleBoard,
    BehanceBoard,
    CoroflotBoard,
    DiceBoard,
    YCombinatorBoard,
]


def _convert(raw, board_name: str) -> JobListing:
    """Convert a legacy dataclass JobListing to a Pydantic JobListing."""
    return JobListing(
        url=raw.url,
        title=raw.title,
        company=raw.company,
        board=board_name,
        location=raw.location or None,
        remote=getattr(raw, "remote", "").lower() in ("yes", "true", "remote") if isinstance(getattr(raw, "remote", ""), str) else bool(getattr(raw, "remote", False)),
        compensation=raw.compensation or None,
        description=raw.description or "",
    )


async def scrape_boards(ctx: RunContext, criteria: SearchCriteria) -> ScrapeResult:
    """Scrape all boards in parallel and return a unified listing set.

    Args:
        ctx: PydanticAI run context (carries BridgeDeps).
        criteria: Loaded SearchCriteria from config/job-search/criteria.json.

    Returns:
        ScrapeResult with listings from all boards that succeeded.
    """
    keywords = criteria.keyword_list()

    async def _fetch_board(board_cls):
        board = board_cls()
        try:
            raw_listings = await board.fetch(keywords=keywords, location=criteria.location)
            return board.name, [_convert(r, board.name) for r in raw_listings], None
        except Exception as exc:
            log.warning("Board %s failed: %s", board_cls.__name__, exc)
            return getattr(board_cls, "name", board_cls.__name__), [], str(exc)

    results = await asyncio.gather(*[_fetch_board(cls) for cls in _BOARD_CLASSES])

    all_listings: list[JobListing] = []
    boards_queried: list[str] = []
    error_boards: list[str] = []

    for board_name, listings, err in results:
        boards_queried.append(board_name)
        if err:
            error_boards.append(board_name)
        else:
            all_listings.extend(listings)

    log.info("scrape_boards: %d listings from %d boards (%d errors)", len(all_listings), len(boards_queried), len(error_boards))
    return ScrapeResult(
        listings=all_listings,
        boards_queried=boards_queried,
        error_boards=error_boards,
    )
