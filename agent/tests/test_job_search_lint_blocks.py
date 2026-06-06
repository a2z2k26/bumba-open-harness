"""Sprint 02.10 Phase 2 — lint_cover_letter blocks bad letters in BOTH paths.

Path A: ``teams.tools._job_search.generate_cover_letter`` returns
        success=False when the lint gate fails, and bumps ``lint_failed`` on
        the funnel.

Path B: ``JobSearchAgent._cover_letter_phase`` skips the listing when the
        gate fails — the cover_letter column stays empty so submit can not
        run on that listing.
"""
from __future__ import annotations


import pytest

from job_search import quality_wiring
from job_search.funnel import FunnelStore, today_key


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BUMBA_JOB_SEARCH_DATA_DIR", str(tmp_path))
    quality_wiring.reset_caches()
    yield tmp_path
    quality_wiring.reset_caches()


# A letter long enough to pass word_count (>= 150), but contains an
# unresolved ``[COMPANY]`` placeholder. This is the canonical disaster case
# the spec calls out.
_BAD_LETTER = (
    "Dear hiring manager at [COMPANY],\n\n"
    "I am writing to apply for the open position. "
    "I have many years of experience designing for the web and would love "
    "to contribute to your team. I am skilled in React, TypeScript, and "
    "Figma. I have shipped many products and led design at multiple "
    "companies. I would be excited to discuss the role further. "
    "I have included my resume for review and look forward to hearing from "
    "you. Thank you for your consideration. I am available for a call any "
    "weekday afternoon. Please reach out at your convenience and I will "
    "respond promptly. I am genuinely excited about this opportunity. "
    "I bring a deep portfolio of shipped product work spanning consumer "
    "marketplaces, developer tools, and enterprise dashboards. "
    "I have led cross-functional teams of designers, engineers, and "
    "product managers through ambiguous discovery phases into shipped "
    "production releases. I have worked on accessibility, internationalization, "
    "and performance-critical interfaces. My approach blends typography, "
    "interaction design, and motion to communicate hierarchy and state. "
    "I would welcome a conversation about how this background maps to the "
    "challenges facing the team today and the next twelve months of work.\n\n"
    "Sincerely,\nTest"
)


class TestPathAGenerateCoverLetterLintGate:
    @pytest.mark.asyncio
    async def test_unresolved_placeholder_blocks_path_a(
        self, isolated_data_dir, monkeypatch
    ):
        from teams.tools._job_search import generate_cover_letter

        # Patch the generator to return a letter with an unresolved
        # ``[COMPANY]`` token.
        async def fake_gen(listing, candidate):  # noqa: ARG001
            return _BAD_LETTER

        # candidate loader returns a stub
        class _Cand:
            pass

        monkeypatch.setattr(
            "job_search.cover_letter.generate_cover_letter", fake_gen
        )
        # The fix/path-a-import-bugs branch replaced the dead
        # ``criteria.load_candidate`` reference with the canonical
        # ``Candidate.from_file(DEFAULT_CANDIDATE)`` call. Stub the
        # classmethod so the lint gate code path is reachable on dev hosts
        # that don't ship ``agent/job_search/candidate.json``.
        from job_search.criteria import Candidate
        monkeypatch.setattr(
            Candidate, "from_file", classmethod(lambda cls, path: _Cand())
        )

        class _Ctx:
            deps = None

        result = await generate_cover_letter(
            _Ctx(),
            job_title="Designer",
            company="Stripe",
            description="design",
            url="https://example.com",
        )

        assert result["success"] is False
        assert result["cover_letter"] is None
        assert "lint_failed" in (result["error"] or "")
        assert "placeholder_token" in result.get("lint_failures", [])

        # Funnel records the failure.
        store = FunnelStore(isolated_data_dir)
        day = store.get(today_key())
        assert day.lint_failed == 1
        assert day.lint_passed == 0
        assert day.covered == 0

    @pytest.mark.asyncio
    async def test_clean_letter_passes_path_a(self, isolated_data_dir, monkeypatch):
        from teams.tools._job_search import generate_cover_letter

        good_letter = _BAD_LETTER.replace("[COMPANY]", "Stripe")

        async def fake_gen(listing, candidate):  # noqa: ARG001
            return good_letter

        class _Cand:
            pass

        monkeypatch.setattr(
            "job_search.cover_letter.generate_cover_letter", fake_gen
        )
        # The fix/path-a-import-bugs branch replaced the dead
        # ``criteria.load_candidate`` reference with the canonical
        # ``Candidate.from_file(DEFAULT_CANDIDATE)`` call. Stub the
        # classmethod so the lint gate code path is reachable on dev hosts
        # that don't ship ``agent/job_search/candidate.json``.
        from job_search.criteria import Candidate
        monkeypatch.setattr(
            Candidate, "from_file", classmethod(lambda cls, path: _Cand())
        )

        class _Ctx:
            deps = None

        result = await generate_cover_letter(
            _Ctx(),
            job_title="Designer",
            company="Stripe",
            description="design",
            url="https://example.com",
        )

        assert result["success"] is True
        assert result["cover_letter"] == good_letter

        store = FunnelStore(isolated_data_dir)
        day = store.get(today_key())
        assert day.lint_passed == 1
        assert day.covered == 1
        assert day.lint_failed == 0


class TestPathBAgentLintGate:
    @pytest.mark.asyncio
    async def test_lint_failure_skips_persist_path_b(
        self, isolated_data_dir, tmp_path, monkeypatch
    ):
        from job_search.agent import JobSearchAgent
        from job_search.boards.base import JobListing

        criteria_file = tmp_path / "criteria.json"
        criteria_file.write_text(
            '{"keywords": [], "exclusions": [], "roles": [], "seniority": [], '
            '"location": "", "daily_cap": 50}'
        )
        candidate_file = tmp_path / "candidate.json"
        candidate_file.write_text(
            '{"name": "Test", "email": "t@t.com", "phone": "", '
            '"resume_path": "", "linkedin": "", "github": "", '
            '"portfolio": "", "cover_letter_mode": "ai_generated", '
            '"location": "", "work_authorization": "", "salary_expectation": "", '
            '"willing_to_relocate": false, "preferred_remote": false}'
        )

        async def fake_gen(listing, candidate):  # noqa: ARG001
            return _BAD_LETTER  # contains [COMPANY] placeholder

        monkeypatch.setattr("job_search.agent.generate_cover_letter", fake_gen)

        db_path = tmp_path / "test.db"
        agent = JobSearchAgent(
            criteria_path=criteria_file,
            candidate_path=candidate_file,
            db_path=db_path,
            data_dir=isolated_data_dir,
        )
        conn = agent._init_db()
        try:
            listing = JobListing(
                url="https://example.com/job/1",
                title="Designer",
                company="Stripe",
                board="remotive",
                description="d",
            )
            # Insert listing as 'new'.
            agent._save_listing(conn, listing, "greenhouse", "fp1")

            # Run the cover letter phase with a single (fp, listing, ats) tuple.
            res = await agent._cover_letter_phase(conn, [("fp1", listing, "greenhouse")])
            assert res["generated"] == 0
            assert res["lint_failed"] == 1

            # Cover letter column must remain NULL/empty (submit phase will skip).
            row = conn.execute(
                "SELECT cover_letter FROM job_listings WHERE fingerprint = 'fp1'"
            ).fetchone()
            assert not row[0]
        finally:
            conn.close()

        store = FunnelStore(isolated_data_dir)
        day = store.get(today_key())
        assert day.lint_failed == 1
        assert day.lint_passed == 0
