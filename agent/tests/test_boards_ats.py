"""Tests for ATS-direct scrapers (Sprint 06.05+).

Covers:
- ``boards/_ats_api.py`` shared HTTP + retry helper.
- ``boards/ashby_jobs.py`` Ashby scraper end-to-end (config load, parse,
  rate limit, graceful degradation).

Greenhouse (06.06) and Lever (06.07) tests will land in this file as
those sprints ship.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from job_search.boards import _ats_api
from job_search.boards.ashby_jobs import AshbyJobsBoard
from job_search.boards.greenhouse_jobs import GreenhouseBoard
from job_search.boards.lever_jobs import LeverBoard


# --- Fixtures ----------------------------------------------------------------

ASHBY_RESPONSE_TEMPLATE: dict[str, Any] = {
    "jobs": [
        {
            "id": "ramp-1",
            "title": "Senior Design Engineer",
            "departmentName": "Design",
            "locationName": "Remote, US",
            "workplaceType": "Remote",
            "employmentType": "FullTime",
            "jobUrl": "https://jobs.ashbyhq.com/ramp/1",
            "applyUrl": "https://jobs.ashbyhq.com/ramp/1/apply",
            "descriptionPlain": "Build delightful design tooling for the Ramp product team.",
            "compensation": {
                "compensationTierSummary": "$180,000 - $230,000 USD",
                "compensationTiers": [
                    {"tierSummary": "$180,000 - $230,000 USD"},
                ],
            },
        },
        {
            "id": "ramp-2",
            "title": "Backend Engineer",
            "departmentName": "Platform",
            "locationName": "New York, NY",
            "workplaceType": "Hybrid",
            "jobUrl": "https://jobs.ashbyhq.com/ramp/2",
            "descriptionPlain": "Scale our infrastructure.",
        },
    ]
}


GREENHOUSE_RESPONSE_TEMPLATE: dict[str, Any] = {
    "jobs": [
        {
            "id": 1001,
            "title": "Senior Design Engineer",
            "absolute_url": "https://boards.greenhouse.io/stripe/jobs/1001",
            "location": {"name": "Remote, US"},
            "content": (
                "<p>Build delightful design tooling for the Stripe product team.</p>"
                "<ul><li>5+ years experience</li></ul>"
            ),
            "company": {"name": "Stripe"},
            "departments": [{"name": "Design"}],
        },
        {
            "id": 1002,
            "title": "Backend Engineer",
            "absolute_url": "https://boards.greenhouse.io/stripe/jobs/1002",
            "location": {"name": "New York, NY"},
            "content": "<p>Scale our payments infrastructure.</p>",
            "company": {"name": "Stripe"},
        },
    ]
}


# Lever's response is a TOP-LEVEL JSON ARRAY of postings — that's the
# key shape difference from Ashby/Greenhouse which both wrap in a
# ``{"jobs": [...]}`` envelope.
LEVER_RESPONSE_TEMPLATE: list[dict[str, Any]] = [
    {
        "id": "netflix-1",
        "text": "Senior Design Engineer",
        "hostedUrl": "https://jobs.lever.co/netflix/1",
        "applyUrl": "https://jobs.lever.co/netflix/1/apply",
        "categories": {
            "location": "Remote — US",
            "team": "Design",
            "commitment": "Full-time",
        },
        "workplaceType": "remote",
        "descriptionPlain": "Build delightful design tooling for the streaming product.",
        "description": "<p>Build delightful design tooling for the streaming product.</p>",
        "salaryRange": {"min": 180000, "max": 230000, "currency": "USD"},
        "company": "Netflix",
    },
    {
        "id": "netflix-2",
        "text": "Backend Engineer",
        "hostedUrl": "https://jobs.lever.co/netflix/2",
        "categories": {"location": "Los Gatos, CA", "team": "Platform"},
        "workplaceType": "on-site",
        "descriptionPlain": "Scale our streaming infrastructure.",
    },
]


def _write_companies(
    tmp_path: Path,
    ashby: list[dict[str, str]] | None = None,
    *,
    greenhouse: list[dict[str, str]] | None = None,
    lever: list[dict[str, str]] | None = None,
) -> Path:
    config_path = tmp_path / "companies.yaml"
    import yaml
    config_path.write_text(
        yaml.safe_dump(
            {
                "ashby": ashby or [],
                "greenhouse": greenhouse or [],
                "lever": lever or [],
            }
        )
    )
    return config_path


# --- _ats_api helper tests ---------------------------------------------------


class TestAtsApiHelper:
    """Sprint 06.05 — shared HTTP + retry helper."""

    @pytest.mark.asyncio
    async def test_returns_parsed_json_on_200(self):
        with patch("job_search.boards._ats_api.aiohttp.ClientSession") as mock_session_cls:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"jobs": [{"title": "x"}]})
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=False)

            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=mock_response)
            mock_session.close = AsyncMock()
            mock_session_cls.return_value = mock_session

            result = await _ats_api.fetch_with_retry("https://example.invalid/x")
            assert result == {"jobs": [{"title": "x"}]}

    @pytest.mark.asyncio
    async def test_returns_none_on_4xx_without_retry(self):
        attempts = 0

        with patch("job_search.boards._ats_api.aiohttp.ClientSession") as mock_session_cls:
            mock_response = MagicMock()
            mock_response.status = 404
            mock_response.json = AsyncMock(return_value=None)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=False)

            def get(*_args, **_kwargs):
                nonlocal attempts
                attempts += 1
                return mock_response

            mock_session = MagicMock()
            mock_session.get = MagicMock(side_effect=get)
            mock_session.close = AsyncMock()
            mock_session_cls.return_value = mock_session

            result = await _ats_api.fetch_with_retry("https://example.invalid/missing")
            assert result is None
            assert attempts == 1  # 4xx is terminal — no retry

    @pytest.mark.asyncio
    async def test_retries_on_500_then_succeeds(self):
        responses_status = [500, 500, 200]
        attempts = 0

        with patch("job_search.boards._ats_api.aiohttp.ClientSession") as mock_session_cls:
            with patch("job_search.boards._ats_api.asyncio.sleep", new=AsyncMock()):
                def get(*_args, **_kwargs):
                    nonlocal attempts
                    response = MagicMock()
                    response.status = responses_status[attempts]
                    response.json = AsyncMock(return_value={"jobs": []})
                    response.__aenter__ = AsyncMock(return_value=response)
                    response.__aexit__ = AsyncMock(return_value=False)
                    attempts += 1
                    return response

                mock_session = MagicMock()
                mock_session.get = MagicMock(side_effect=get)
                mock_session.close = AsyncMock()
                mock_session_cls.return_value = mock_session

                result = await _ats_api.fetch_with_retry(
                    "https://example.invalid/flaky",
                    max_retries=3,
                )
                assert result == {"jobs": []}
                assert attempts == 3

    @pytest.mark.asyncio
    async def test_gives_up_after_max_retries_on_5xx(self):
        attempts = 0

        with patch("job_search.boards._ats_api.aiohttp.ClientSession") as mock_session_cls:
            with patch("job_search.boards._ats_api.asyncio.sleep", new=AsyncMock()):
                def get(*_args, **_kwargs):
                    nonlocal attempts
                    response = MagicMock()
                    response.status = 500
                    response.json = AsyncMock(return_value=None)
                    response.__aenter__ = AsyncMock(return_value=response)
                    response.__aexit__ = AsyncMock(return_value=False)
                    attempts += 1
                    return response

                mock_session = MagicMock()
                mock_session.get = MagicMock(side_effect=get)
                mock_session.close = AsyncMock()
                mock_session_cls.return_value = mock_session

                result = await _ats_api.fetch_with_retry(
                    "https://example.invalid/down",
                    max_retries=3,
                )
                assert result is None
                assert attempts == 3


# --- Ashby scraper tests -----------------------------------------------------


class TestAshbyJobsBoard:
    """Sprint 06.05 — Ashby ATS scraper."""

    @pytest.mark.asyncio
    async def test_no_companies_returns_empty(self, tmp_path):
        config_path = _write_companies(tmp_path, [])
        board = AshbyJobsBoard(
            companies_config_path=config_path,
            rate_limit_seconds=0,
        )
        result = await board.fetch(keywords=["design"])
        assert result == []

    @pytest.mark.asyncio
    async def test_missing_config_returns_empty(self, tmp_path):
        board = AshbyJobsBoard(
            companies_config_path=tmp_path / "missing.yaml",
            rate_limit_seconds=0,
        )
        result = await board.fetch(keywords=["design"])
        assert result == []

    @pytest.mark.asyncio
    async def test_parses_seed_companies_into_listings(self, tmp_path):
        config_path = _write_companies(
            tmp_path, [{"token": "ramp", "name": "Ramp"}],
        )
        board = AshbyJobsBoard(
            companies_config_path=config_path,
            rate_limit_seconds=0,
        )
        with patch(
            "job_search.boards.ashby_jobs.fetch_with_retry",
            new=AsyncMock(return_value=ASHBY_RESPONSE_TEMPLATE),
        ):
            result = await board.fetch(keywords=["design"])

        assert len(result) == 1  # only "Senior Design Engineer" matches keyword
        listing = result[0]
        assert listing.title == "Senior Design Engineer"
        assert listing.company == "Ramp"  # falls back to display name
        assert listing.board == "ashby"
        assert listing.url == "https://jobs.ashbyhq.com/ramp/1"
        assert listing.remote == "yes"
        assert "180,000" in listing.compensation
        assert "Build delightful design tooling" in listing.description

    @pytest.mark.asyncio
    async def test_handles_404_gracefully(self, tmp_path):
        config_path = _write_companies(
            tmp_path, [{"token": "missing-org", "name": "Missing"}],
        )
        board = AshbyJobsBoard(
            companies_config_path=config_path,
            rate_limit_seconds=0,
        )
        with patch(
            "job_search.boards.ashby_jobs.fetch_with_retry",
            new=AsyncMock(return_value=None),
        ):
            result = await board.fetch(keywords=["design"])
        assert result == []  # 404 → None → skipped, no crash

    @pytest.mark.asyncio
    async def test_handles_empty_jobs_array(self, tmp_path):
        config_path = _write_companies(
            tmp_path, [{"token": "noopenings", "name": "NoOpenings"}],
        )
        board = AshbyJobsBoard(
            companies_config_path=config_path,
            rate_limit_seconds=0,
        )
        with patch(
            "job_search.boards.ashby_jobs.fetch_with_retry",
            new=AsyncMock(return_value={"jobs": []}),
        ):
            result = await board.fetch(keywords=["design"])
        assert result == []

    @pytest.mark.asyncio
    async def test_keyword_filter_strips_non_matching(self, tmp_path):
        config_path = _write_companies(
            tmp_path, [{"token": "ramp", "name": "Ramp"}],
        )
        board = AshbyJobsBoard(
            companies_config_path=config_path,
            rate_limit_seconds=0,
        )
        with patch(
            "job_search.boards.ashby_jobs.fetch_with_retry",
            new=AsyncMock(return_value=ASHBY_RESPONSE_TEMPLATE),
        ):
            # Keyword "backend" matches the second job title only
            result = await board.fetch(keywords=["backend"])
        assert len(result) == 1
        assert result[0].title == "Backend Engineer"

    @pytest.mark.asyncio
    async def test_respects_rate_limit_between_companies(self, tmp_path):
        config_path = _write_companies(
            tmp_path,
            [
                {"token": "ramp", "name": "Ramp"},
                {"token": "linear", "name": "Linear"},
            ],
        )
        board = AshbyJobsBoard(
            companies_config_path=config_path,
            rate_limit_seconds=0.05,
        )
        sleep_calls: list[float] = []

        async def fake_sleep(d):
            sleep_calls.append(d)

        with patch(
            "job_search.boards.ashby_jobs.fetch_with_retry",
            new=AsyncMock(return_value={"jobs": []}),
        ):
            with patch.object(asyncio, "sleep", new=fake_sleep):
                await board.fetch(keywords=[])

        # First company has no preceding sleep; second triggers one rate-limit
        # sleep at the configured interval.
        assert sleep_calls == [0.05]


# --- Greenhouse scraper tests -----------------------------------------------


class TestGreenhouseBoard:
    """Sprint 06.06 — Greenhouse ATS scraper."""

    @pytest.mark.asyncio
    async def test_no_companies_returns_empty(self, tmp_path):
        config_path = _write_companies(tmp_path, greenhouse=[])
        board = GreenhouseBoard(
            companies_config_path=config_path,
            rate_limit_seconds=0,
        )
        result = await board.fetch(keywords=["design"])
        assert result == []

    @pytest.mark.asyncio
    async def test_parses_seed_companies_into_listings(self, tmp_path):
        config_path = _write_companies(
            tmp_path,
            greenhouse=[{"token": "stripe", "name": "Stripe"}],
        )
        board = GreenhouseBoard(
            companies_config_path=config_path,
            rate_limit_seconds=0,
        )
        with patch(
            "job_search.boards.greenhouse_jobs.fetch_with_retry",
            new=AsyncMock(return_value=GREENHOUSE_RESPONSE_TEMPLATE),
        ):
            result = await board.fetch(keywords=["design"])

        assert len(result) == 1  # only "Senior Design Engineer" matches keyword
        listing = result[0]
        assert listing.title == "Senior Design Engineer"
        assert listing.company == "Stripe"
        assert listing.board == "greenhouse"
        assert listing.url == "https://boards.greenhouse.io/stripe/jobs/1001"
        assert listing.location == "Remote, US"
        assert listing.remote == "yes"
        assert listing.compensation == ""  # Greenhouse has no structured comp
        assert "Build delightful design tooling" in listing.description
        # HTML tags must be stripped from the description preview.
        assert "<p>" not in listing.description
        assert "<ul>" not in listing.description
        # Raw payload must drop the bulky ``content`` blob.
        assert "content" not in listing.raw

    @pytest.mark.asyncio
    async def test_handles_403_gracefully(self, tmp_path):
        config_path = _write_companies(
            tmp_path,
            greenhouse=[{"token": "private-org", "name": "PrivateOrg"}],
        )
        board = GreenhouseBoard(
            companies_config_path=config_path,
            rate_limit_seconds=0,
        )
        # ``fetch_with_retry`` returns ``None`` for any 4xx (per _ats_api).
        with patch(
            "job_search.boards.greenhouse_jobs.fetch_with_retry",
            new=AsyncMock(return_value=None),
        ):
            result = await board.fetch(keywords=["design"])
        assert result == []  # 403 → None → skipped, no crash

    @pytest.mark.asyncio
    async def test_handles_empty_jobs_array(self, tmp_path):
        config_path = _write_companies(
            tmp_path,
            greenhouse=[{"token": "noopenings", "name": "NoOpenings"}],
        )
        board = GreenhouseBoard(
            companies_config_path=config_path,
            rate_limit_seconds=0,
        )
        with patch(
            "job_search.boards.greenhouse_jobs.fetch_with_retry",
            new=AsyncMock(return_value={"jobs": []}),
        ):
            result = await board.fetch(keywords=["design"])
        assert result == []

    @pytest.mark.asyncio
    async def test_keyword_filter_strips_non_matching(self, tmp_path):
        config_path = _write_companies(
            tmp_path,
            greenhouse=[{"token": "stripe", "name": "Stripe"}],
        )
        board = GreenhouseBoard(
            companies_config_path=config_path,
            rate_limit_seconds=0,
        )
        with patch(
            "job_search.boards.greenhouse_jobs.fetch_with_retry",
            new=AsyncMock(return_value=GREENHOUSE_RESPONSE_TEMPLATE),
        ):
            # Keyword "backend" matches the second job title only.
            result = await board.fetch(keywords=["backend"])
        assert len(result) == 1
        assert result[0].title == "Backend Engineer"
        assert result[0].remote == ""  # New York, NY → not remote


# --- Lever scraper tests -----------------------------------------------------


class TestLeverBoard:
    """Sprint 06.07 — Lever ATS scraper."""

    @pytest.mark.asyncio
    async def test_no_companies_returns_empty(self, tmp_path):
        config_path = _write_companies(tmp_path, lever=[])
        board = LeverBoard(
            companies_config_path=config_path,
            rate_limit_seconds=0,
        )
        result = await board.fetch(keywords=["design"])
        assert result == []

    @pytest.mark.asyncio
    async def test_parses_seed_companies_into_listings(self, tmp_path):
        config_path = _write_companies(
            tmp_path,
            lever=[{"token": "netflix", "name": "Netflix"}],
        )
        board = LeverBoard(
            companies_config_path=config_path,
            rate_limit_seconds=0,
        )
        with patch(
            "job_search.boards.lever_jobs.fetch_with_retry",
            new=AsyncMock(return_value=LEVER_RESPONSE_TEMPLATE),
        ):
            result = await board.fetch(keywords=["design"])

        assert len(result) == 1  # only "Senior Design Engineer" matches keyword
        listing = result[0]
        assert listing.title == "Senior Design Engineer"
        assert listing.company == "Netflix"
        assert listing.board == "lever"
        assert listing.url == "https://jobs.lever.co/netflix/1"
        assert listing.location == "Remote — US"
        assert listing.remote == "yes"
        # Compensation formatted from salaryRange min/max/currency
        assert "$180,000" in listing.compensation
        assert "$230,000" in listing.compensation
        assert "USD" in listing.compensation
        # descriptionPlain preferred over description (HTML)
        assert "Build delightful design tooling" in listing.description
        # Description fields excluded from raw payload
        assert "description" not in listing.raw
        assert "descriptionPlain" not in listing.raw

    @pytest.mark.asyncio
    async def test_handles_404_gracefully(self, tmp_path):
        config_path = _write_companies(
            tmp_path,
            lever=[{"token": "missing-org", "name": "Missing"}],
        )
        board = LeverBoard(
            companies_config_path=config_path,
            rate_limit_seconds=0,
        )
        with patch(
            "job_search.boards.lever_jobs.fetch_with_retry",
            new=AsyncMock(return_value=None),
        ):
            result = await board.fetch(keywords=["design"])
        assert result == []  # 404 → None → skipped, no crash

    @pytest.mark.asyncio
    async def test_handles_top_level_non_list_response(self, tmp_path):
        """Defensive: if Lever ever returned a dict, parse must not crash."""
        config_path = _write_companies(
            tmp_path,
            lever=[{"token": "weird-org", "name": "Weird"}],
        )
        board = LeverBoard(
            companies_config_path=config_path,
            rate_limit_seconds=0,
        )
        with patch(
            "job_search.boards.lever_jobs.fetch_with_retry",
            new=AsyncMock(return_value={"unexpected": "shape"}),
        ):
            result = await board.fetch(keywords=["design"])
        assert result == []

    @pytest.mark.asyncio
    async def test_keyword_filter_strips_non_matching(self, tmp_path):
        config_path = _write_companies(
            tmp_path,
            lever=[{"token": "netflix", "name": "Netflix"}],
        )
        board = LeverBoard(
            companies_config_path=config_path,
            rate_limit_seconds=0,
        )
        with patch(
            "job_search.boards.lever_jobs.fetch_with_retry",
            new=AsyncMock(return_value=LEVER_RESPONSE_TEMPLATE),
        ):
            # "backend" matches the second posting only
            result = await board.fetch(keywords=["backend"])
        assert len(result) == 1
        assert result[0].title == "Backend Engineer"
        assert result[0].remote == ""  # workplaceType=on-site, location=Los Gatos
        assert result[0].compensation == ""  # no salaryRange on posting #2
