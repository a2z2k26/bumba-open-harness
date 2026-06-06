"""Regression tests for the Path A (Z4 director tools) import surface.

Sprint 02.10's audit of Path A found three pre-existing ``ImportError`` /
``AttributeError`` failures plus a missing ``job_search.models`` module.
Together they meant Path A — ``teams/tools/_job_search.py`` and the
pass-through shims under ``job_search/tools/`` — could not be imported,
which silently blocked the canonical tool path that Plan 04 will activate.

These tests pin the fix in place. If anyone reverts the field rename, the
candidate loader, the YC class import, or the ``models`` module, one of
the four assertions below will fire at collection time.
"""
from __future__ import annotations


def test_job_search_tools_boards_imports_cleanly() -> None:
    """``job_search.tools.boards`` must import without raising and expose
    ``YCombinatorBoard`` (the actual class name in
    ``job_search.boards.yc_workatastartup``; the legacy import used the
    non-existent ``YCBoard`` and crashed at module load)."""
    import job_search.tools.boards as boards  # noqa: F401 — import is the assertion

    assert "YCombinatorBoard" in boards.__dict__, (
        "boards.py must import YCombinatorBoard (not the bogus YCBoard)"
    )


def test_teams_tools_job_search_imports_cleanly() -> None:
    """``teams.tools._job_search`` is the canonical Path A entry point.

    It re-imports ``job_search.tools.boards`` and ``job_search.tools.scoring``
    inside its tool functions, so a clean module-level import here is the
    proof that nothing in the transitive surface raises at first touch.
    """
    import teams.tools._job_search as path_a  # noqa: F401 — import is the assertion

    # Canonical tool functions must be exported at module scope so the Z4
    # registry can pick them up.
    for fn_name in (
        "scrape_boards",
        "score_and_deduplicate",
        "generate_cover_letter",
        "stage_listing_to_notion",
    ):
        assert hasattr(path_a, fn_name), f"Path A must expose {fn_name}"


def test_search_criteria_construction_uses_correct_field() -> None:
    """``SearchCriteria`` is a dataclass whose role-list field is ``roles``,
    NOT ``keywords``. The pre-fix code passed ``keywords=...`` which raised
    ``TypeError: SearchCriteria.__init__() got an unexpected keyword
    argument 'keywords'`` at runtime."""
    from job_search.criteria import SearchCriteria

    # Correct field name: ``roles``. Construction must not raise.
    crit = SearchCriteria(roles=["Product Designer", "UX Designer"])
    assert crit.roles == ["Product Designer", "UX Designer"]
    # ``keyword_list()`` is what downstream board code consumes; it returns
    # roles + field-relevant root words.
    assert "designer" in crit.keyword_list()
    assert "Product Designer" in crit.keyword_list()


def test_load_candidate_alternative() -> None:
    """The pre-fix code imported a non-existent ``load_candidate`` function
    from ``job_search.criteria``. The canonical replacement is
    ``Candidate.from_file(DEFAULT_CANDIDATE)`` — the same construction the
    legacy ``JobSearchAgent`` uses on agent.py:84.

    We do not require the on-disk JSON to exist (the runtime host has it,
    dev hosts may not), so we exercise an inline ``Candidate(...)``
    construction instead — this is the shape Path A relies on after the
    import resolves.
    """
    from job_search.agent import DEFAULT_CANDIDATE  # noqa: F401 — verify import path
    from job_search.criteria import Candidate

    # Build a candidate inline (matches Candidate.from_file's output shape).
    c = Candidate(
        name="the operator",
        email="operator@example.com",
        years_experience=10,
        skills=["design", "engineering"],
    )
    assert isinstance(c, Candidate)
    assert c.name == "the operator"
    assert c.years_experience == 10

    # ``from_file`` is the canonical loader; verify the classmethod exists
    # and is callable. We don't invoke it because the JSON config lives on
    # the runtime host only.
    assert callable(Candidate.from_file)


def test_job_search_models_surface() -> None:
    """``job_search.models`` is a new module added in this fix. It supplies
    the Pydantic ``JobListing`` / ``ScrapeResult`` / ``ScoredListings``
    types that the tool shims and the Z4 entry point both import.

    Pre-fix: this module was missing on origin/main, so importing the
    shims raised ``ModuleNotFoundError: No module named 'job_search.models'``.
    """
    from job_search.models import JobListing, ScoredListings, ScrapeResult

    # JobListing must round-trip through model_dump / model_copy.
    jl = JobListing(url="https://example.com/x", title="Designer", company="Co")
    payload = jl.model_dump()
    assert payload["score"] == 0
    bumped = jl.model_copy(update={"score": 42})
    assert bumped.score == 42

    # ScrapeResult and ScoredListings must default to empty containers.
    assert ScrapeResult().listings == []
    assert ScoredListings().total_scraped == 0
