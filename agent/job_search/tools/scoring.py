"""Z4 Tool: score_and_deduplicate — canonical implementation.

This module IS the canonical implementation; the chief-side wrapper at
``teams/tools/_job_search.py::score_and_deduplicate`` imports from here.

(Mirrors the HI-15 docstring fix in ``boards.py``; both shims claimed the
inverse of reality.)
"""
from __future__ import annotations

import logging
import re

from pydantic_ai import RunContext

from job_search.criteria import SearchCriteria
from job_search.deduplication import Deduplicator
from job_search.models import JobListing, ScoredListings

log = logging.getLogger(__name__)

# Keywords that boost a listing's score
_TITLE_BOOST: dict[str, int] = {
    "lead": 10,
    "staff": 10,
    "principal": 10,
    "director": 8,
    "head of": 8,
    "senior": 5,
    "sr.": 5,
}

_COMP_BOOST_THRESHOLD = 120_000  # USD — listings mentioning >$120k get a bonus

# HI-12 (#1881) — compensation-floor filter.
#
# Compensation arrives as free-text from boards: "$150,000 - $180,000",
# "150k - 180k", "USD 150000+", etc. Extract every plausible USD figure
# from the string and use the MAX as the listing's effective top-end.
# Use the max so a wide range like "$120k - $200k" is judged on the
# upper bound (matches the README's "filter out listings BELOW this"
# spec — a listing topping out at $200k clears a $150k floor).
#
# Fail-open: a listing with no parseable compensation passes the filter.
# Boards frequently omit comp on the listing page, and dropping every
# listing with empty comp would lose ~50%+ of legitimate hits.
_USD_RE = re.compile(
    r"""
    \$?\s*                  # optional leading $
    (\d{2,3}(?:,\d{3})+)    # 12,345 or 123,456 (must have at least one comma group)
    |                       # OR
    \$?\s*                  # optional leading $
    (\d{2,3})\s*[kK]\b      # 120k / 175K
    |                       # OR
    \$?\s*                  # optional leading $
    (\d{5,7})\b             # bare 150000 / 1500000 (5-7 digits avoids zip codes)
    """,
    re.VERBOSE,
)


def _max_compensation_usd(comp: str) -> int | None:
    """Extract the highest plausible USD figure from a free-text comp string.

    Returns ``None`` when no figure parses. Handles:
        "$150,000 - $180,000"   → 180000
        "150k - 180k"           → 180000
        "USD 175,000"           → 175000
        ""                      → None
        "Competitive"           → None
    """
    if not comp:
        return None
    candidates: list[int] = []
    for m in _USD_RE.finditer(comp):
        commas, k_form, bare = m.groups()
        try:
            if commas is not None:
                candidates.append(int(commas.replace(",", "")))
            elif k_form is not None:
                candidates.append(int(k_form) * 1000)
            elif bare is not None:
                candidates.append(int(bare))
        except ValueError:
            continue
    if not candidates:
        return None
    return max(candidates)


def _score(listing: JobListing, criteria: SearchCriteria) -> int:
    """Compute a relevance score for a single listing."""
    score = 0
    title_lower = listing.title.lower()

    # Role match
    for role in criteria.roles:
        if role.lower() in title_lower:
            score += 20
            break

    # Seniority match
    for level in criteria.seniority:
        if level.lower() in title_lower:
            score += 10
            break

    # Title keyword boost
    for kw, pts in _TITLE_BOOST.items():
        if kw in title_lower:
            score += pts
            break

    # Remote preference
    if criteria.remote_only and listing.remote:
        score += 5

    # Compensation signal
    comp = listing.compensation or ""
    if any(str(n) in comp.replace(",", "") for n in range(_COMP_BOOST_THRESHOLD // 1000, 500)):
        score += 10

    # Exclusion penalty — if any exclusion keyword appears in title or description
    if criteria.matches_exclusions(listing.title) or criteria.matches_exclusions(listing.description[:500]):
        score -= 50

    return max(score, 0)


async def score_and_deduplicate(
    ctx: RunContext,
    listings: list[JobListing],
    criteria: SearchCriteria,
    seen_fingerprints: set[str] | None = None,
) -> ScoredListings:
    """Score listings and remove duplicates.

    Args:
        ctx: PydanticAI run context.
        listings: Raw listings from scrape_boards.
        criteria: Loaded criteria for scoring rules.
        seen_fingerprints: Optional set of fingerprints already in the DB (for cross-run dedup).

    Returns:
        ScoredListings sorted by score descending.
    """
    dedup = Deduplicator()
    if seen_fingerprints:
        for fp in seen_fingerprints:
            dedup.add_fingerprint(fp)

    total_scraped = len(listings)
    unique: list[JobListing] = []
    duplicate_count = 0

    for listing in listings:
        if dedup.is_duplicate(listing.url, listing.title, listing.company):
            duplicate_count += 1
            continue
        dedup.mark_seen(listing.url, listing.title, listing.company)
        unique.append(listing)

    total_after_dedup = len(unique)

    # HI-12 (#1881) — apply compensation floor BEFORE scoring. Fail-open
    # for listings whose comp string doesn't parse (board omitted comp,
    # "Competitive", "DOE", etc.). The floor is a hard filter; the score
    # path's $120k boost remains independent.
    floor = criteria.compensation_floor_usd
    floor_filtered_count = 0
    if floor > 0:
        floor_pass: list[JobListing] = []
        for listing in unique:
            comp_max = _max_compensation_usd(listing.compensation or "")
            if comp_max is not None and comp_max < floor:
                floor_filtered_count += 1
                continue
            floor_pass.append(listing)
        unique = floor_pass

    total_after_floor = len(unique)

    # Score and filter out exclusions
    scored: list[JobListing] = []
    filtered_count = 0
    for listing in unique:
        s = _score(listing, criteria)
        if s > 0:
            listing = listing.model_copy(update={"score": s})
            scored.append(listing)
        else:
            filtered_count += 1

    # Sort by score desc
    scored.sort(key=lambda l: l.score, reverse=True)

    log.info(
        "score_and_deduplicate: %d scraped -> %d unique -> %d after floor "
        "-> %d scored (dupes=%d, floor_dropped=%d, score_filtered=%d)",
        total_scraped, total_after_dedup, total_after_floor, len(scored),
        duplicate_count, floor_filtered_count, filtered_count,
    )

    return ScoredListings(
        listings=scored,
        total_scraped=total_scraped,
        total_after_dedup=total_after_dedup,
        total_after_scoring=len(scored),
        duplicate_count=duplicate_count,
        filtered_count=filtered_count,
    )
