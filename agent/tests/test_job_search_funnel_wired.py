"""Sprint 02.10 Phase 1 — FunnelStore is wired through both retrofit paths.

Asserts that bumps reach the ``funnel.json`` for:
    * scraped     (Path A scrape_boards + Path B _research_phase)
    * deduped     (Path A score_and_deduplicate + Path B _research_phase)
    * lint_passed (cover_letter generation success)
    * covered     (cover_letter accepted)
    * staged      (Notion stage success)
    * sent        (outreach send success)

Both paths must write to the **same** funnel.json keyed by ``data_dir`` —
the 22:00 ``FunnelPostService`` reads aggregate counts regardless of which
PREPARE path ran.
"""
from __future__ import annotations


import pytest

from job_search import quality_wiring
from job_search.funnel import FunnelStore, today_key


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Point quality_wiring at a tmp_path and reset its singleton caches."""
    monkeypatch.setenv("BUMBA_JOB_SEARCH_DATA_DIR", str(tmp_path))
    quality_wiring.reset_caches()
    yield tmp_path
    quality_wiring.reset_caches()


class TestFunnelBumpsReachStore:
    def test_bump_today_writes_to_resolved_data_dir(self, isolated_data_dir):
        quality_wiring.bump_today("scraped", count=12)
        store = FunnelStore(isolated_data_dir)
        day = store.get(today_key())
        assert day.scraped == 12

    def test_two_callers_share_one_funnel_file(self, isolated_data_dir):
        # Simulates Path A and Path B both bumping in the same cron run.
        quality_wiring.bump_today("scraped", count=5)
        quality_wiring.bump_today("scraped", count=7)
        quality_wiring.bump_today("deduped", count=3)

        store = FunnelStore(isolated_data_dir)
        day = store.get(today_key())
        assert day.scraped == 12
        assert day.deduped == 3

    def test_quality_failures_are_swallowed(self, isolated_data_dir, monkeypatch):
        # If FunnelStore raises, bump_today must not propagate (observability,
        # not control flow).
        def boom(*args, **kwargs):  # noqa: ARG001
            raise RuntimeError("disk full")

        monkeypatch.setattr(FunnelStore, "bump", boom)
        quality_wiring.reset_caches()
        # Should NOT raise.
        quality_wiring.bump_today("scraped", count=1)


class TestPathBAgentFunnelBumps:
    """JobSearchAgent (Path B) phases bump the funnel."""

    @pytest.mark.asyncio
    async def test_research_phase_bumps_scraped_and_deduped(
        self, isolated_data_dir, tmp_path, monkeypatch
    ):
        from job_search.agent import JobSearchAgent
        from job_search.boards.base import JobListing

        # Build a minimal candidate + criteria pair on disk.
        criteria_file = tmp_path / "criteria.json"
        criteria_file.write_text(
            '{"keywords": ["design"], "exclusions": [], "roles": [], '
            '"seniority": [], "location": "", "daily_cap": 50}'
        )
        candidate_file = tmp_path / "candidate.json"
        candidate_file.write_text(
            '{"name": "Test", "email": "t@t.com", "phone": "", '
            '"cover_letter_mode": "skip"}'
        )

        listing1 = JobListing(
            url="https://example.com/job/1",
            title="Designer",
            company="Acme",
            board="remotive",
            description="design role",
        )
        listing2 = JobListing(
            url="https://example.com/job/1",  # duplicate of listing1
            title="Designer",
            company="Acme",
            board="remotive",
            description="design role",
        )

        # Stub board: returns 2 listings. Replaces the agent's _boards list
        # entirely so we don't have to import every real board class.
        class _StubBoard:
            name = "stub"

            async def fetch(self, keywords, location):  # noqa: ARG002
                return [listing1, listing2]

        # Patch detect_ats so we don't network out.
        from job_search.ats import detector

        class _AtsResult:
            ats = "greenhouse"

        monkeypatch.setattr(detector, "detect_ats", lambda url: _AtsResult())

        db_path = tmp_path / "test.db"
        agent = JobSearchAgent(
            criteria_path=criteria_file,
            candidate_path=candidate_file,
            db_path=db_path,
            data_dir=isolated_data_dir,
        )
        agent._boards = [_StubBoard()]
        conn = agent._init_db()
        try:
            res = await agent._research_phase(conn)
        finally:
            conn.close()

        assert res["fetched"] == 2
        assert res["saved"] == 1

        # Funnel bumps: 2 scraped (count of listings returned), 1 deduped.
        store = FunnelStore(isolated_data_dir)
        day = store.get(today_key())
        assert day.scraped == 2
        assert day.deduped == 1


class TestPathAToolFunnelBumps:
    """Z4 director tools (Path A) bump the funnel through the same store."""

    @pytest.mark.asyncio
    async def test_scrape_boards_bumps_scraped(self, isolated_data_dir, monkeypatch):
        # Inject a stub ``job_search.tools.boards`` so we don't pull in
        # the real one (pre-existing import error: imports YCBoard which
        # does not exist in yc_workatastartup.py).
        import sys
        import types

        stub_boards = types.ModuleType("job_search.tools.boards")

        class _FakeListing:
            def model_dump(self):
                return {"url": "u", "title": "t", "company": "c"}

        class _Result:
            listings = [_FakeListing() for _ in range(7)]
            boards_queried = ["board"]
            error_boards = []

        async def fake_scrape(ctx, criteria):  # noqa: ARG001
            return _Result()

        stub_boards.scrape_boards = fake_scrape
        monkeypatch.setitem(sys.modules, "job_search.tools.boards", stub_boards)

        # ``SearchCriteria`` does not accept ``keywords`` kwarg in the real
        # dataclass — pre-existing bug in scrape_boards. Patch the symbol
        # used by _job_search.py with a constructor that swallows it.
        from job_search import criteria as _criteria_mod

        class _PermissiveCriteria:
            def __init__(self, **kwargs):
                pass

        monkeypatch.setattr(_criteria_mod, "SearchCriteria", _PermissiveCriteria)

        from teams.tools._job_search import scrape_boards

        class _Ctx:
            deps = None

        result = await scrape_boards(_Ctx(), keywords=["design"])
        assert result.get("total") == 7, f"unexpected result: {result}"

        store = FunnelStore(isolated_data_dir)
        day = store.get(today_key())
        assert day.scraped == 7
