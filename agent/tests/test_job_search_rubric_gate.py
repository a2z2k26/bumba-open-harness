"""Sprint 06.03 — rubric gate inside ``JobSearchAgent._research_phase`` +
``_apply_rubric_gate`` filter inside ``prepare()``.

Spec: docs/specs/2026-04-25-reference-audit/spec-06-03-insert-rubric-gate-inside-researchphase-filter-toplistings.md

Coverage:
    * Schema migration is idempotent (run _init_db twice → no error).
    * ``_research_phase`` writes rubric columns when the flag is True.
    * ``_research_phase`` skips rubric (writes None) when the flag is False
      (regression guard — default cron path stays free).
    * ``_apply_rubric_gate`` filters listings below the configured threshold.
    * ``_apply_rubric_gate`` returns BOTH ``passed`` and ``filtered`` so the
      filtered set still flows into Notion staging.
    * Threshold "A" filters more aggressively than "B".
    * Cover-letter loop runs only on ``passed`` (verified via call counter).
    * Disabled flag → no rubric eval invocations (regression guard).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from job_search import quality_wiring
from job_search.boards.base import JobListing
from job_search.rubric import RubricResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """Point quality_wiring at a tmp_path so funnel writes don't leak."""
    monkeypatch.setenv("BUMBA_JOB_SEARCH_DATA_DIR", str(tmp_path))
    quality_wiring.reset_caches()
    yield tmp_path
    quality_wiring.reset_caches()


@pytest.fixture
def _criteria_file(tmp_path: Path) -> Path:
    p = tmp_path / "criteria.json"
    p.write_text(
        '{"keywords": ["design"], "exclusions": [], "roles": [], '
        '"seniority": [], "location": "", "daily_cap": 50}'
    )
    return p


@pytest.fixture
def _candidate_file(tmp_path: Path) -> Path:
    p = tmp_path / "candidate.json"
    p.write_text(
        '{"name": "Test", "email": "t@t.com", "phone": "", '
        '"cover_letter_mode": "skip"}'
    )
    return p


@pytest.fixture
def _rubric_yaml(tmp_path: Path) -> Path:
    """Two-dimension rubric whose weights sum to 1.0."""
    p = tmp_path / "rubric.yaml"
    p.write_text(
        """
dimensions:
  - name: dim-a
    weight: 0.5
    eval_prompt_fragment: "Question A?"
    score_anchors:
      1: low
      5: high
    letter_grade_thresholds: &t
      A: 4.5
      B: 3.5
      C: 2.5
      D: 1.5
      F: 0.0
  - name: dim-b
    weight: 0.5
    eval_prompt_fragment: "Question B?"
    score_anchors:
      1: low
      5: high
    letter_grade_thresholds: *t
""".lstrip()
    )
    return p


def _listing(idx: int = 1, **overrides: Any) -> JobListing:
    defaults: dict[str, Any] = {
        "url": f"https://example.com/job/{idx}",
        "title": f"Designer {idx}",
        "company": f"Co{idx}",
        "board": "remotive",
        "description": f"design role {idx}",
    }
    defaults.update(overrides)
    return JobListing(**defaults)


def _rubric_result(grade: str, score: float = 4.0) -> RubricResult:
    return RubricResult(
        letter_grade=grade,
        weighted_score=score,
        per_dim_scores={"dim-a": int(score), "dim-b": int(score)},
        per_dim_rationale={"dim-a": "ok", "dim-b": "ok"},
        model_used="claude-haiku-4-5",
        cost_usd=0.01,
        evaluated_at=datetime.now(timezone.utc),
    )


def _patch_detect_ats(monkeypatch) -> None:
    """``detect_ats`` runs HTTP — replace with a deterministic stub."""
    from job_search.ats import detector

    class _AtsResult:
        ats = "greenhouse"

    monkeypatch.setattr(detector, "detect_ats", lambda url: _AtsResult())


def _build_agent(
    *,
    criteria_file: Path,
    candidate_file: Path,
    db_path: Path,
    data_dir: Path,
    rubric_path: Path | None = None,
    enabled: bool = False,
    threshold: str = "B",
):
    from job_search.agent import JobSearchAgent

    return JobSearchAgent(
        criteria_path=criteria_file,
        candidate_path=candidate_file,
        db_path=db_path,
        data_dir=data_dir,
        rubric_gate_enabled=enabled,
        rubric_threshold=threshold,
        rubric_path=rubric_path,
    )


# ---------------------------------------------------------------------------
# Schema migration is idempotent
# ---------------------------------------------------------------------------


class TestSchemaMigrationIdempotent:
    def test_init_db_twice_does_not_error(
        self, tmp_path, _criteria_file, _candidate_file, _isolated_data_dir
    ):
        agent = _build_agent(
            criteria_file=_criteria_file,
            candidate_file=_candidate_file,
            db_path=tmp_path / "test.db",
            data_dir=_isolated_data_dir,
            enabled=False,
        )
        conn1 = agent._init_db()
        conn1.close()
        # Re-running _init_db on the populated DB must not raise.
        conn2 = agent._init_db()
        try:
            cursor = conn2.execute("PRAGMA table_info(job_listings)")
            cols = {row[1] for row in cursor.fetchall()}
            for expected in (
                "rubric_grade", "rubric_score",
                "rubric_rationale", "rubric_evaluated_at",
            ):
                assert expected in cols, f"missing column {expected!r}"
        finally:
            conn2.close()


# ---------------------------------------------------------------------------
# _research_phase rubric write paths
# ---------------------------------------------------------------------------


class TestResearchPhaseRubricColumns:
    @pytest.mark.asyncio
    async def test_research_phase_writes_rubric_when_flag_on(
        self,
        tmp_path,
        _criteria_file,
        _candidate_file,
        _rubric_yaml,
        _isolated_data_dir,
        monkeypatch,
    ):
        _patch_detect_ats(monkeypatch)

        # Stub rubric.evaluate so we don't spawn claude subprocesses.
        async def _fake_eval(listing, candidate, rubric_def, **kw):
            return _rubric_result("A", score=4.8)

        monkeypatch.setattr("job_search.agent.rubric_evaluate", _fake_eval)

        class _StubBoard:
            name = "stub"

            async def fetch(self, keywords, location):  # noqa: ARG002
                return [_listing(1)]

        agent = _build_agent(
            criteria_file=_criteria_file,
            candidate_file=_candidate_file,
            db_path=tmp_path / "test.db",
            data_dir=_isolated_data_dir,
            rubric_path=_rubric_yaml,
            enabled=True,
            threshold="B",
        )
        agent._boards = [_StubBoard()]

        conn = agent._init_db()
        try:
            res = await agent._research_phase(conn)
            assert res["fetched"] == 1
            assert res["saved"] == 1

            row = conn.execute(
                "SELECT rubric_grade, rubric_score, rubric_rationale, rubric_evaluated_at "
                "FROM job_listings"
            ).fetchone()
            grade, score, rationale, evaluated_at = row
            assert grade == "A"
            assert score == pytest.approx(4.8)
            assert rationale  # non-empty JSON
            assert evaluated_at  # ISO timestamp string
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_research_phase_skips_rubric_when_flag_off(
        self,
        tmp_path,
        _criteria_file,
        _candidate_file,
        _isolated_data_dir,
        monkeypatch,
    ):
        """Regression guard: the cron must not pay the Haiku cost when the
        gate is disabled, and the rubric columns must stay NULL."""
        _patch_detect_ats(monkeypatch)

        # Booby-trap rubric_evaluate so a stray call would explode.
        async def _boom(*args, **kw):  # pragma: no cover — must not fire
            raise AssertionError("rubric_evaluate must not be called when flag is off")

        monkeypatch.setattr("job_search.agent.rubric_evaluate", _boom)

        class _StubBoard:
            name = "stub"

            async def fetch(self, keywords, location):  # noqa: ARG002
                return [_listing(1)]

        agent = _build_agent(
            criteria_file=_criteria_file,
            candidate_file=_candidate_file,
            db_path=tmp_path / "test.db",
            data_dir=_isolated_data_dir,
            enabled=False,
        )
        agent._boards = [_StubBoard()]

        conn = agent._init_db()
        try:
            await agent._research_phase(conn)
            row = conn.execute(
                "SELECT rubric_grade, rubric_score FROM job_listings"
            ).fetchone()
            assert row[0] is None
            assert row[1] is None
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# _apply_rubric_gate
# ---------------------------------------------------------------------------


def _seed_listing_with_grade(conn, agent, idx: int, grade: str | None) -> tuple:
    """Insert a listing + (optionally) a rubric grade. Returns (fp, listing, ats)."""
    listing = _listing(idx)
    fp = f"fp{idx}"
    rubric = _rubric_result(grade, score=4.0) if grade is not None else None
    agent._save_listing(conn, listing, "greenhouse", fp, rubric=rubric)
    return (fp, listing, "greenhouse")


class TestApplyRubricGate:
    def test_disabled_flag_returns_all_in_passed(
        self, tmp_path, _criteria_file, _candidate_file, _isolated_data_dir
    ):
        agent = _build_agent(
            criteria_file=_criteria_file,
            candidate_file=_candidate_file,
            db_path=tmp_path / "test.db",
            data_dir=_isolated_data_dir,
            enabled=False,
        )
        conn = agent._init_db()
        try:
            entries = [
                _seed_listing_with_grade(conn, agent, 1, None),
                _seed_listing_with_grade(conn, agent, 2, None),
            ]
            passed, filtered = agent._apply_rubric_gate(conn, entries)
            assert passed == entries
            assert filtered == []
        finally:
            conn.close()

    def test_threshold_b_filters_below_b(
        self, tmp_path, _criteria_file, _candidate_file, _rubric_yaml, _isolated_data_dir
    ):
        agent = _build_agent(
            criteria_file=_criteria_file,
            candidate_file=_candidate_file,
            db_path=tmp_path / "test.db",
            data_dir=_isolated_data_dir,
            rubric_path=_rubric_yaml,
            enabled=True,
            threshold="B",
        )
        conn = agent._init_db()
        try:
            a = _seed_listing_with_grade(conn, agent, 1, "A")
            b = _seed_listing_with_grade(conn, agent, 2, "B")
            c = _seed_listing_with_grade(conn, agent, 3, "C")
            d = _seed_listing_with_grade(conn, agent, 4, "D")

            passed, filtered = agent._apply_rubric_gate(conn, [a, b, c, d])
            passed_fps = {x[0] for x in passed}
            filtered_fps = {x[0] for x in filtered}
            assert passed_fps == {"fp1", "fp2"}
            assert filtered_fps == {"fp3", "fp4"}
        finally:
            conn.close()

    @pytest.mark.parametrize(
        "threshold,passing,filtering",
        [
            ("A", {"A"}, {"B", "C"}),       # A is strictest
            ("B", {"A", "B"}, {"C"}),       # default
            ("C", {"A", "B", "C"}, set()),  # liberal
        ],
    )
    def test_threshold_a_more_aggressive_than_b(
        self,
        tmp_path,
        _criteria_file,
        _candidate_file,
        _rubric_yaml,
        _isolated_data_dir,
        threshold,
        passing,
        filtering,
    ):
        agent = _build_agent(
            criteria_file=_criteria_file,
            candidate_file=_candidate_file,
            db_path=tmp_path / "test.db",
            data_dir=_isolated_data_dir,
            rubric_path=_rubric_yaml,
            enabled=True,
            threshold=threshold,
        )
        conn = agent._init_db()
        try:
            entries = [
                _seed_listing_with_grade(conn, agent, 1, "A"),
                _seed_listing_with_grade(conn, agent, 2, "B"),
                _seed_listing_with_grade(conn, agent, 3, "C"),
            ]
            passed, filtered = agent._apply_rubric_gate(conn, entries)
            grade_for_fp = {"fp1": "A", "fp2": "B", "fp3": "C"}
            assert {grade_for_fp[x[0]] for x in passed} == passing
            assert {grade_for_fp[x[0]] for x in filtered} == filtering
        finally:
            conn.close()

    def test_missing_grade_falls_into_filtered(
        self, tmp_path, _criteria_file, _candidate_file, _rubric_yaml, _isolated_data_dir
    ):
        """When the gate is enabled but a row has no grade, fail-closed."""
        agent = _build_agent(
            criteria_file=_criteria_file,
            candidate_file=_candidate_file,
            db_path=tmp_path / "test.db",
            data_dir=_isolated_data_dir,
            rubric_path=_rubric_yaml,
            enabled=True,
            threshold="B",
        )
        conn = agent._init_db()
        try:
            entries = [
                _seed_listing_with_grade(conn, agent, 1, None),
                _seed_listing_with_grade(conn, agent, 2, "A"),
            ]
            passed, filtered = agent._apply_rubric_gate(conn, entries)
            assert {x[0] for x in passed} == {"fp2"}
            assert {x[0] for x in filtered} == {"fp1"}
        finally:
            conn.close()

    def test_returns_both_passed_and_filtered_for_notion_staging(
        self, tmp_path, _criteria_file, _candidate_file, _rubric_yaml, _isolated_data_dir
    ):
        """Filtered listings are NOT discarded — caller stages them in Notion."""
        agent = _build_agent(
            criteria_file=_criteria_file,
            candidate_file=_candidate_file,
            db_path=tmp_path / "test.db",
            data_dir=_isolated_data_dir,
            rubric_path=_rubric_yaml,
            enabled=True,
            threshold="A",
        )
        conn = agent._init_db()
        try:
            entries = [
                _seed_listing_with_grade(conn, agent, 1, "A"),
                _seed_listing_with_grade(conn, agent, 2, "C"),
            ]
            passed, filtered = agent._apply_rubric_gate(conn, entries)
            # Both buckets are populated — the filtered listing is preserved
            # so 06.04 can stage it in Notion with its rubric data.
            assert len(passed) == 1 and len(filtered) == 1
            assert passed[0][0] == "fp1"
            assert filtered[0][0] == "fp2"
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Cover-letter loop runs only on `passed`
# ---------------------------------------------------------------------------


class TestCoverLetterLoopOnlyOnPassed:
    @pytest.mark.asyncio
    async def test_filtered_listings_skip_cover_letter_phase(
        self,
        tmp_path,
        _rubric_yaml,
        _isolated_data_dir,
        monkeypatch,
    ):
        """End-to-end: prepare() with the gate ON skips cover letters for
        filtered listings and runs them only on passed listings."""
        # Force ai_generated mode so the cover-letter phase actually loops.
        criteria_file = tmp_path / "criteria.json"
        criteria_file.write_text(
            '{"keywords": ["design"], "exclusions": [], "roles": [], '
            '"seniority": [], "location": "", "daily_cap": 50}'
        )
        candidate_file = tmp_path / "candidate.json"
        candidate_file.write_text(
            '{"name": "Test", "email": "t@t.com", "phone": "", '
            '"cover_letter_mode": "ai_generated"}'
        )

        _patch_detect_ats(monkeypatch)

        # First listing → grade A, second → grade C (below "B" threshold).
        grades_iter = iter(["A", "C"])

        async def _fake_eval(listing, candidate, rubric_def, **kw):
            return _rubric_result(next(grades_iter), score=4.0)

        monkeypatch.setattr("job_search.agent.rubric_evaluate", _fake_eval)

        # Counter for cover-letter generation.
        cover_calls: list[str] = []

        async def _fake_cover(listing, candidate):  # noqa: ARG001
            cover_calls.append(listing.title)
            return f"Dear {listing.company},\n\nI am applying."

        monkeypatch.setattr("job_search.agent.generate_cover_letter", _fake_cover)

        # Lint passes so the cover letter persists.
        from job_search import agent as agent_mod

        class _LintOK:
            ok = True
            failures: list[str] = []

        monkeypatch.setattr(
            agent_mod, "lint_cover_letter",
            lambda cl, company: _LintOK(),
        )

        # Stub submit / outreach research / drafts / staging — they only
        # need to not blow up the prepare() flow.
        async def _noop_submit(conn, listings):  # noqa: ARG001
            return {"submitted": 0, "blocked": 0, "failed": 0, "attempted": len(listings)}

        async def _noop_outreach_research(conn, listings):  # noqa: ARG001
            return {"total_contacts": 0, "failed_companies": 0, "attempted": len(listings)}

        async def _noop_outreach_drafts(conn, listings):  # noqa: ARG001
            return {"drafted": 0}

        async def _noop_staging(conn, listings):  # noqa: ARG001
            return {"staged": len(listings), "errors": 0, "total": len(listings)}

        # Stub board returning two listings.
        class _StubBoard:
            name = "stub"

            async def fetch(self, keywords, location):  # noqa: ARG002
                return [_listing(1, title="Pass-Me"), _listing(2, title="Filter-Me")]

        agent = _build_agent(
            criteria_file=criteria_file,
            candidate_file=candidate_file,
            db_path=tmp_path / "test.db",
            data_dir=_isolated_data_dir,
            rubric_path=_rubric_yaml,
            enabled=True,
            threshold="B",
        )
        agent._boards = [_StubBoard()]
        # Patch instance-bound methods that would otherwise need network.
        agent._submit_phase = AsyncMock(side_effect=_noop_submit)
        agent._outreach_research_phase = AsyncMock(side_effect=_noop_outreach_research)
        agent._outreach_draft_phase = AsyncMock(side_effect=_noop_outreach_drafts)
        agent._staging_phase = AsyncMock(side_effect=_noop_staging)

        summary = await agent.prepare()

        # Cover-letter generator was called exactly once — for the passing
        # listing. The filtered listing must NOT have triggered a call.
        assert cover_calls == ["Pass-Me"]

        # Submit / outreach also operate on passed only (1 listing).
        agent._submit_phase.assert_awaited_once()
        _, submitted_arg = agent._submit_phase.await_args.args
        assert len(submitted_arg) == 1

        # Staging operates on the FULL top_listings (passed + filtered).
        agent._staging_phase.assert_awaited_once()
        _, staged_arg = agent._staging_phase.await_args.args
        assert len(staged_arg) == 2

        gate = summary["phases"]["rubric_gate"]
        assert gate["passed"] == 1
        assert gate["filtered"] == 1
        assert gate["enabled"] is True
        assert gate["threshold"] == "B"


# ---------------------------------------------------------------------------
# BridgeConfig flag mapping
# ---------------------------------------------------------------------------


class TestBridgeConfigFlag:
    def test_default_flag_off(self):
        from bridge.config import BridgeConfig

        c = BridgeConfig()
        assert c.job_search_rubric_gate_enabled is False
        assert c.job_search_rubric_threshold == "B"

    def test_toml_mapping(self, tmp_path):
        from bridge.config import load_config

        toml = tmp_path / "bridge.toml"
        toml.write_text(
            '[job_search]\n'
            'rubric_gate_enabled = true\n'
            'rubric_threshold = "A"\n'
        )
        c = load_config(toml, skip_secrets=True, skip_validation=True)
        assert c.job_search_rubric_gate_enabled is True
        assert c.job_search_rubric_threshold == "A"
