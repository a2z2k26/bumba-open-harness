"""Pydantic models used by the Z4 job-search tool shims.

The legacy pipeline (``job_search/agent.py``) operates on the dataclass
``JobListing`` defined in :mod:`job_search.boards.base`. The Z4 tool shims
(``job_search/tools/boards.py`` and ``job_search/tools/scoring.py``) and the
canonical Path A entry point (``teams/tools/_job_search.py``) expect a
Pydantic model with ``.model_dump()`` / ``.model_copy(update=...)`` semantics
so tool outputs round-trip cleanly through PydanticAI's tool-call protocol.

This module supplies that Pydantic surface. Field names mirror the legacy
dataclass (so :func:`job_search.tools.boards._convert` continues to work)
plus a ``score`` field that ``score_and_deduplicate`` populates.

Until 2026-04-25 this module was missing, which left both Path A entry
points raising ``ModuleNotFoundError`` at first import — surfaced during
Sprint 02.10's Path A audit alongside the other pre-existing import bugs
fixed in this commit.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class JobListing(BaseModel):
    """Pydantic mirror of the legacy ``boards.base.JobListing`` dataclass.

    Permissive defaults match the legacy dataclass so converter code
    (e.g. ``boards.py::_convert``) can pass ``None`` for absent fields.
    """

    url: str
    title: str
    company: str
    board: str = ""
    location: Optional[str] = None
    remote: bool = False
    compensation: Optional[str] = None
    description: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)
    score: int = 0


class ScrapeResult(BaseModel):
    """Result of a multi-board scrape run."""

    listings: list[JobListing] = Field(default_factory=list)
    boards_queried: list[str] = Field(default_factory=list)
    error_boards: list[str] = Field(default_factory=list)


class ScoredListings(BaseModel):
    """Result of the score + dedup pass over a raw listing set."""

    listings: list[JobListing] = Field(default_factory=list)
    total_scraped: int = 0
    total_after_dedup: int = 0
    total_after_scoring: int = 0
    duplicate_count: int = 0
    filtered_count: int = 0
