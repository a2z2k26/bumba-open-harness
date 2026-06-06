"""Tests for ProjectPulseService (Z2-S5.4)."""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.services.project_pulse import (
    ProjectPulseService,
    _bucket_prs,
    _format_repo_section,
    STALE_DAYS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def svc(tmp_dir):
    return ProjectPulseService(
        data_dir=tmp_dir,
        chat_id="ch-pulse",
        repos=["your-org/bumba-open-harness", "your-org/business"],
    )


# ---------------------------------------------------------------------------
# _bucket_prs
# ---------------------------------------------------------------------------

class TestBucketPrs:
    def _make_pr(self, age_days: int) -> dict:
        created = (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()
        return {"number": 1, "title": "Test PR", "created_at": created,
                "user": "alice", "requested_reviewers": []}

    def test_fresh_pr_in_0_7d_bucket(self):
        buckets = _bucket_prs([self._make_pr(3)])
        assert len(buckets["0-7d"]) == 1
        assert len(buckets["7-14d"]) == 0

    def test_week_old_pr_in_7_14d_bucket(self):
        buckets = _bucket_prs([self._make_pr(10)])
        assert len(buckets["7-14d"]) == 1

    def test_month_old_pr_in_14_30d_bucket(self):
        buckets = _bucket_prs([self._make_pr(20)])
        assert len(buckets["14-30d"]) == 1

    def test_very_old_pr_in_30plus_bucket(self):
        buckets = _bucket_prs([self._make_pr(60)])
        assert len(buckets["30+d"]) == 1

    def test_empty_list(self):
        buckets = _bucket_prs([])
        assert all(len(v) == 0 for v in buckets.values())

    def test_unparseable_date_goes_to_30plus(self):
        pr = {"number": 2, "title": "Bad date", "created_at": "invalid-date",
              "user": "bob", "requested_reviewers": []}
        buckets = _bucket_prs([pr])
        assert len(buckets["30+d"]) == 1


# ---------------------------------------------------------------------------
# _format_repo_section
# ---------------------------------------------------------------------------

class TestFormatRepoSection:
    def _empty_buckets(self):
        return {"0-7d": [], "7-14d": [], "14-30d": [], "30+d": []}

    def test_recent_commit_not_stale(self):
        last_commit = datetime.now(timezone.utc) - timedelta(days=3)
        section = _format_repo_section("org/repo", last_commit, self._empty_buckets(), 2)
        assert "STALE" not in section

    def test_old_commit_stale(self):
        last_commit = datetime.now(timezone.utc) - timedelta(days=STALE_DAYS + 1)
        section = _format_repo_section("org/repo", last_commit, self._empty_buckets(), 0)
        assert "STALE" in section

    def test_unknown_last_commit_stale(self):
        section = _format_repo_section("org/repo", None, self._empty_buckets(), 0)
        assert "STALE" in section

    def test_shows_branch_count(self):
        last_commit = datetime.now(timezone.utc) - timedelta(days=1)
        section = _format_repo_section("org/repo", last_commit, self._empty_buckets(), 5)
        assert "5" in section

    def test_short_name_used(self):
        last_commit = datetime.now(timezone.utc) - timedelta(days=1)
        section = _format_repo_section("owner/myrepo", last_commit, self._empty_buckets(), 0)
        assert "myrepo" in section
        assert "owner" not in section


# ---------------------------------------------------------------------------
# ProjectPulseService.should_run
# ---------------------------------------------------------------------------

class TestShouldRun:
    def test_runs_when_no_prior_run(self, svc):
        assert svc.should_run() is True

    def test_skips_when_already_ran_today(self, svc):
        state = svc.load_state("project-pulse-state.json")
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        svc.save_state(state, "project-pulse-state.json")
        assert svc.should_run() is False

    def test_runs_when_last_run_yesterday(self, svc):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        state = svc.load_state("project-pulse-state.json")
        state["last_run"] = yesterday
        svc.save_state(state, "project-pulse-state.json")
        assert svc.should_run() is True


# ---------------------------------------------------------------------------
# ProjectPulseService.build_report
# ---------------------------------------------------------------------------

class TestBuildReport:
    def _mock_gh(self, last_commit_dt, prs, branch_count):
        """Patch all three gh helper functions."""
        return (
            patch("bridge.services.project_pulse._last_commit_date",
                  return_value=last_commit_dt),
            patch("bridge.services.project_pulse._open_prs",
                  return_value=prs),
            patch("bridge.services.project_pulse._open_branch_count",
                  return_value=branch_count),
        )

    def test_report_contains_all_repos(self, svc):
        last_commit = datetime.now(timezone.utc) - timedelta(days=2)
        with patch("bridge.services.project_pulse._last_commit_date", return_value=last_commit), \
             patch("bridge.services.project_pulse._open_prs", return_value=[]), \
             patch("bridge.services.project_pulse._open_branch_count", return_value=3):
            report = svc.build_report(["your-org/bumba-open-harness", "your-org/business"])
        assert "bumba-open-harness" in report
        assert "business" in report

    def test_stale_repo_flagged(self, svc):
        old_commit = datetime.now(timezone.utc) - timedelta(days=20)
        with patch("bridge.services.project_pulse._last_commit_date", return_value=old_commit), \
             patch("bridge.services.project_pulse._open_prs", return_value=[]), \
             patch("bridge.services.project_pulse._open_branch_count", return_value=0):
            report = svc.build_report(["your-org/business"])
        assert "STALE" in report

    def test_partial_failure_handled(self, svc):
        """If one repo raises, the report still includes the others."""
        call_count = [0]

        def side_effect(repo):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("gh rate limit")
            return datetime.now(timezone.utc) - timedelta(days=1)

        with patch("bridge.services.project_pulse._last_commit_date",
                   side_effect=side_effect), \
             patch("bridge.services.project_pulse._open_prs", return_value=[]), \
             patch("bridge.services.project_pulse._open_branch_count", return_value=0):
            report = svc.build_report(["your-org/bumba-open-harness", "your-org/business"])
        assert "data unavailable" in report or "business" in report

    def test_report_has_header(self, svc):
        with patch("bridge.services.project_pulse._last_commit_date",
                   return_value=datetime.now(timezone.utc) - timedelta(days=1)), \
             patch("bridge.services.project_pulse._open_prs", return_value=[]), \
             patch("bridge.services.project_pulse._open_branch_count", return_value=0):
            report = svc.build_report(["your-org/bumba-open-harness"])
        assert "Project Pulse" in report


# ---------------------------------------------------------------------------
# ProjectPulseService.run
# ---------------------------------------------------------------------------

class TestRun:
    def test_run_skip_when_already_ran(self, svc):
        state = svc.load_state("project-pulse-state.json")
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        svc.save_state(state, "project-pulse-state.json")
        result = svc.run()
        assert result.skip_reason == "already_ran_today"

    def test_run_posts_message(self, svc):
        with patch.object(svc, "build_report", return_value="**Project Pulse**\nAll good."):
            result = svc.run()
        assert result.ok is True
        assert result.work_items == 2  # 2 repos in fixture
        msgs = list((Path(svc.data_dir) / "service_messages").glob("*.json"))
        assert len(msgs) >= 1

    def test_run_records_success(self, svc):
        with patch.object(svc, "build_report", return_value="Report"):
            svc.run()
        state = svc.load_state("project-pulse-state.json")
        assert state["last_run"] is not None
        assert state["consecutive_failures"] == 0

    def test_run_narration_present(self, svc):
        with patch.object(svc, "build_report", return_value="Report"):
            result = svc.run()
        assert result.narration is not None
        assert "2" in result.narration  # 2 repos
