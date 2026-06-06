"""Tests for the Z4 job-search scoring shim."""

import pytest

from job_search.criteria import SearchCriteria
from job_search.models import JobListing
from job_search.tools.scoring import (
    _max_compensation_usd,
    _score,
    score_and_deduplicate,
)


def _criteria() -> SearchCriteria:
    return SearchCriteria(
        roles=["Product Designer"],
        seniority=["lead", "senior"],
        exclusions=["casino"],
        remote_only=True,
    )


def _listing(**kwargs) -> JobListing:
    defaults = {
        "url": "https://example.com/jobs/1",
        "title": "Lead Product Designer",
        "company": "Acme",
        "board": "greenhouse",
        "remote": True,
        "compensation": "$150,000",
        "description": "Design systems and product experience.",
    }
    defaults.update(kwargs)
    return JobListing(**defaults)


def test_score_combines_role_seniority_remote_and_compensation() -> None:
    score = _score(_listing(), _criteria())
    assert score == 55


def test_score_applies_exclusion_floor() -> None:
    listing = _listing(
        title="Casino Floor Operator",
        compensation="",
        description="casino gaming operations",
    )
    assert _score(listing, _criteria()) == 0


@pytest.mark.asyncio
async def test_score_and_deduplicate_counts_unique_duplicate_and_filtered() -> None:
    primary = _listing()
    duplicate = _listing()
    filtered = _listing(
        url="https://example.com/jobs/2",
        title="Casino Floor Operator",
        compensation="",
        description="casino gaming operations",
    )

    result = await score_and_deduplicate(
        ctx=None,
        listings=[primary, duplicate, filtered],
        criteria=_criteria(),
    )

    assert result.total_scraped == 3
    assert result.total_after_dedup == 2
    assert result.total_after_scoring == 1
    assert result.duplicate_count == 1
    assert result.filtered_count == 1
    assert result.listings[0].score == 55


# ---------------------------------------------------------------------------
# HI-12 (#1881) — compensation_floor_usd filter
# ---------------------------------------------------------------------------


class TestMaxCompensationUsd:
    """Parser for the comp-string max-USD extraction."""

    def test_parses_dollar_with_commas(self):
        assert _max_compensation_usd("$150,000") == 150000

    def test_parses_dollar_range_returns_max(self):
        assert _max_compensation_usd("$120,000 - $180,000") == 180000

    def test_parses_k_form(self):
        assert _max_compensation_usd("120k - 175k") == 175000

    def test_parses_bare_number(self):
        assert _max_compensation_usd("USD 150000") == 150000

    def test_returns_none_on_empty(self):
        assert _max_compensation_usd("") is None

    def test_returns_none_on_unparseable(self):
        assert _max_compensation_usd("Competitive salary, DOE") is None

    def test_mixed_format_picks_max(self):
        # A range expressed mixing forms — max wins.
        assert _max_compensation_usd("$120k base, OTE up to $200,000") == 200000


@pytest.mark.asyncio
async def test_compensation_floor_drops_listings_below():
    """Floor is hard filter — listings with parseable comp under floor drop."""
    criteria = SearchCriteria(
        roles=["Product Designer"],
        seniority=["lead", "senior"],
        compensation_floor_usd=150_000,
        remote_only=True,
    )
    high = _listing(url="https://e.com/1", compensation="$180,000")
    low = _listing(url="https://e.com/2", compensation="$80,000")

    result = await score_and_deduplicate(
        ctx=None, listings=[high, low], criteria=criteria,
    )

    assert result.total_scraped == 2
    assert result.total_after_scoring == 1
    assert result.listings[0].compensation == "$180,000"


@pytest.mark.asyncio
async def test_compensation_floor_fail_open_when_unparseable():
    """No parseable comp = pass the floor (fail-open per docstring)."""
    criteria = SearchCriteria(
        roles=["Product Designer"],
        seniority=["lead", "senior"],
        compensation_floor_usd=150_000,
        remote_only=True,
    )
    competitive = _listing(url="https://e.com/1", compensation="Competitive")
    empty = _listing(url="https://e.com/2", compensation="")

    result = await score_and_deduplicate(
        ctx=None, listings=[competitive, empty], criteria=criteria,
    )

    # Both pass the floor; both still need to score > 0 (they do — Lead
    # Product Designer matches role + seniority + remote).
    assert result.total_after_scoring == 2


@pytest.mark.asyncio
async def test_compensation_floor_zero_disables_filter():
    """floor=0 (default) means no filter applied — back-compat."""
    criteria = SearchCriteria(
        roles=["Product Designer"],
        seniority=["lead", "senior"],
        compensation_floor_usd=0,  # disabled
        remote_only=True,
    )
    low = _listing(url="https://e.com/1", compensation="$50,000")

    result = await score_and_deduplicate(
        ctx=None, listings=[low], criteria=criteria,
    )

    # Even though comp is below any reasonable floor, the disabled
    # filter doesn't drop it.
    assert result.total_after_scoring == 1


@pytest.mark.asyncio
async def test_compensation_floor_uses_max_of_range():
    """A range straddling the floor is judged on its top-end."""
    criteria = SearchCriteria(
        roles=["Product Designer"],
        seniority=["lead", "senior"],
        compensation_floor_usd=160_000,
        remote_only=True,
    )
    # Range tops out at $200k; floor is $160k — should pass.
    straddle = _listing(
        url="https://e.com/1", compensation="$140,000 - $200,000",
    )
    # Range tops out at $150k; floor is $160k — should drop.
    too_low = _listing(
        url="https://e.com/2", compensation="$120,000 - $150,000",
    )

    result = await score_and_deduplicate(
        ctx=None, listings=[straddle, too_low], criteria=criteria,
    )

    assert result.total_after_scoring == 1
    assert result.listings[0].url == "https://e.com/1"
