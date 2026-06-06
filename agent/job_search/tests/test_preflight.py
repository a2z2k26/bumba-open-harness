"""Tests for pre-flight validation, phase gates, and audit trail."""

import json
import sqlite3
import pytest
from unittest.mock import patch, MagicMock

from job_search.preflight import (
    phase_gate,
    preflight_check,
    start_audit,
    update_audit,
)


@pytest.fixture
def secrets_file(tmp_path):
    path = tmp_path / ".secrets"
    path.write_text(
        "notion_api_token=ntn_test123\n"
        "claude_oauth_token=oauth_test456\n"
    )
    return path


@pytest.fixture
def criteria_file(tmp_path):
    path = tmp_path / "criteria.json"
    path.write_text(json.dumps({"roles": ["designer"], "keywords": ["design"]}))
    return path


@pytest.fixture
def candidate_file(tmp_path):
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps({"name": "Test", "email": "test@example.com"}))
    return path


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    return d


@pytest.fixture
def audit_db(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE run_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_type TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            phase_results TEXT,
            errors TEXT,
            success INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    return conn


class TestPreflightCheck:
    @patch("job_search.preflight.httpx")
    def test_all_pass(self, mock_httpx, secrets_file, criteria_file, candidate_file, db_path, state_dir):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_httpx.get.return_value = mock_resp

        ok, errors = preflight_check(
            secrets_file, criteria_file, candidate_file, db_path, state_dir
        )
        assert ok is True
        assert errors == []

    def test_missing_secrets_file(self, tmp_path, criteria_file, candidate_file, db_path, state_dir):
        ok, errors = preflight_check(
            tmp_path / "nonexistent", criteria_file, candidate_file, db_path, state_dir
        )
        assert ok is False
        assert any("Secrets file not found" in e for e in errors)

    def test_missing_notion_token(self, tmp_path, criteria_file, candidate_file, db_path, state_dir):
        secrets = tmp_path / ".secrets"
        secrets.write_text("claude_oauth_token=test\n")

        ok, errors = preflight_check(
            secrets, criteria_file, candidate_file, db_path, state_dir
        )
        assert ok is False
        assert any("notion_api_token" in e for e in errors)

    def test_missing_claude_token(self, tmp_path, criteria_file, candidate_file, db_path, state_dir):
        secrets = tmp_path / ".secrets"
        secrets.write_text("notion_api_token=test\n")

        ok, errors = preflight_check(
            secrets, criteria_file, candidate_file, db_path, state_dir
        )
        assert ok is False
        assert any("claude_oauth_token" in e for e in errors)

    def test_missing_criteria(self, secrets_file, tmp_path, candidate_file, db_path, state_dir):
        ok, errors = preflight_check(
            secrets_file, tmp_path / "nope.json", candidate_file, db_path, state_dir
        )
        assert ok is False
        assert any("Criteria config not found" in e for e in errors)

    def test_invalid_criteria_json(self, secrets_file, tmp_path, candidate_file, db_path, state_dir):
        bad = tmp_path / "bad.json"
        bad.write_text("not json")

        ok, errors = preflight_check(
            secrets_file, bad, candidate_file, db_path, state_dir
        )
        assert ok is False
        assert any("Criteria config invalid" in e for e in errors)

    def test_missing_candidate(self, secrets_file, criteria_file, tmp_path, db_path, state_dir):
        ok, errors = preflight_check(
            secrets_file, criteria_file, tmp_path / "nope.json", db_path, state_dir
        )
        assert ok is False
        assert any("Candidate config not found" in e for e in errors)

    @patch("job_search.preflight.httpx")
    def test_notion_api_invalid_token(self, mock_httpx, secrets_file, criteria_file, candidate_file, db_path, state_dir):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_httpx.get.return_value = mock_resp

        ok, errors = preflight_check(
            secrets_file, criteria_file, candidate_file, db_path, state_dir
        )
        assert ok is False
        assert any("invalid (401)" in e for e in errors)

    @patch("job_search.preflight.httpx")
    def test_already_ran_today(self, mock_httpx, secrets_file, criteria_file, candidate_file, db_path, state_dir):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_httpx.get.return_value = mock_resp

        from datetime import date
        state_file = state_dir / "job-search-state.json"
        state_file.write_text(json.dumps({"last_run": date.today().isoformat()}))

        ok, errors = preflight_check(
            secrets_file, criteria_file, candidate_file, db_path, state_dir,
            run_type="prepare",
        )
        assert ok is False
        assert any("Already ran prepare today" in e for e in errors)

    @patch("job_search.preflight.httpx")
    @patch("shutil.which", return_value=None)
    def test_execute_needs_gws_cli(self, mock_which, mock_httpx, secrets_file, criteria_file, candidate_file, db_path, state_dir):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_httpx.get.return_value = mock_resp

        # Also mock Path.is_file to return False for the gws binary
        with patch("job_search.preflight.Path.is_file", return_value=False):
            ok, errors = preflight_check(
                secrets_file, criteria_file, candidate_file, db_path, state_dir,
                run_type="execute",
            )
        assert ok is False
        assert any("gws CLI" in e for e in errors)


class TestPhaseGate:
    def test_research_no_listings(self):
        ok, msg = phase_gate("research", {"fetched": 0, "saved": 0})
        assert ok is False
        assert "No listings fetched" in msg

    def test_research_all_duplicates(self):
        ok, msg = phase_gate("research", {"fetched": 10, "saved": 0})
        assert ok is False
        assert "duplicates" in msg

    def test_research_success(self):
        ok, msg = phase_gate("research", {"fetched": 10, "saved": 3})
        assert ok is True
        assert "3 new listings" in msg

    def test_cover_letters_always_passes(self):
        ok, msg = phase_gate("cover_letters", {"generated": 0})
        assert ok is True

    def test_outreach_research_no_contacts(self):
        ok, msg = phase_gate("outreach_research", {"total_contacts": 0, "failed_companies": 3, "attempted": 3})
        assert ok is False
        assert "no contacts" in msg.lower()

    def test_outreach_research_success(self):
        ok, msg = phase_gate("outreach_research", {"total_contacts": 4, "failed_companies": 1, "attempted": 3})
        assert ok is True

    def test_outreach_research_zero_attempted(self):
        ok, msg = phase_gate("outreach_research", {"total_contacts": 0, "failed_companies": 0, "attempted": 0})
        assert ok is True  # nothing to do, not a failure

    def test_outreach_drafts_always_passes(self):
        ok, msg = phase_gate("outreach_drafts", {"drafted": 0})
        assert ok is True

    def test_staging_success(self):
        ok, msg = phase_gate("staging", {"staged": 3, "errors": 0, "total": 3})
        assert ok is True

    def test_staging_mostly_failed(self):
        ok, msg = phase_gate("staging", {"staged": 1, "errors": 3, "total": 4})
        assert ok is False
        assert "mostly failed" in msg

    def test_unknown_phase_passes(self):
        ok, msg = phase_gate("unknown_phase", {})
        assert ok is True
        assert "no gate defined" in msg


class TestAuditTrail:
    def test_start_audit(self, audit_db):
        audit_id = start_audit(audit_db, "prepare")
        assert audit_id is not None
        assert audit_id > 0

        row = audit_db.execute("SELECT run_type, started_at FROM run_audit WHERE id = ?", (audit_id,)).fetchone()
        assert row[0] == "prepare"
        assert row[1]  # has a timestamp

    def test_update_audit(self, audit_db):
        audit_id = start_audit(audit_db, "execute")
        phase_results = {"research": {"fetched": 10}}
        errors = ["test error"]

        update_audit(audit_db, audit_id, phase_results, errors, success=False)

        row = audit_db.execute(
            "SELECT completed_at, phase_results, errors, success FROM run_audit WHERE id = ?",
            (audit_id,),
        ).fetchone()
        assert row[0]  # completed_at set
        assert json.loads(row[1]) == phase_results
        assert json.loads(row[2]) == ["test error"]
        assert row[3] == 0  # success = False

    def test_audit_success_flag(self, audit_db):
        audit_id = start_audit(audit_db, "prepare")
        update_audit(audit_db, audit_id, {}, [], success=True)

        row = audit_db.execute("SELECT success FROM run_audit WHERE id = ?", (audit_id,)).fetchone()
        assert row[0] == 1
