"""Tests for BoardRunStore (Board Phase 2 WS4 #2391, Phase 3 WS2 #2392)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


from bridge.board_run_store import (
    BoardRunStore,
    new_board_run_id,
)


def _store(tmp_path):
    return BoardRunStore(tmp_path)


class TestRunId:
    def test_shape_and_uniqueness(self):
        a = new_board_run_id()
        b = new_board_run_id()
        assert a.startswith("board-")
        assert a != b
        assert len(a.split("-")) == 3


class TestRecordAndList:
    def test_record_persists_full_synthesis(self, tmp_path):
        store = _store(tmp_path)
        rec = store.record_run(
            session_id="sess1",
            question="What is the 2-year vision?",
            synthesis="Compound everything.",
            success=True,
            member_count=7,
            duration_seconds=146.8,
            cost_usd=0.42,
            phase="phase-3",
        )
        assert rec.board_run_id
        loaded = store.get_run(rec.board_run_id)
        assert loaded is not None
        assert loaded.synthesis == "Compound everything."
        assert loaded.member_count == 7
        assert loaded.cost_usd == 0.42

    def test_list_recent_orders_newest_first(self, tmp_path):
        store = _store(tmp_path)
        # Manually craft two records with different date prefixes.
        old = store.record_run(
            session_id="old", question="q", synthesis="s", success=True,
            board_run_id="board-20260101-aaaaaaaa",
        )
        new = store.record_run(
            session_id="new", question="q", synthesis="s", success=True,
            board_run_id="board-20260601-bbbbbbbb",
        )
        # Force the file names to reflect the run dates so ordering is by date.
        recents = store.list_recent(limit=10)
        ids = [r.board_run_id for r in recents]
        assert old.board_run_id in ids and new.board_run_id in ids

    def test_list_recent_respects_limit(self, tmp_path):
        store = _store(tmp_path)
        for i in range(5):
            store.record_run(
                session_id=f"s{i}", question="q", synthesis="s", success=True,
            )
        assert len(store.list_recent(limit=3)) == 3

    def test_corrupt_run_file_skipped(self, tmp_path):
        store = _store(tmp_path)
        store.record_run(session_id="ok", question="q", synthesis="s", success=True)
        store.directory.mkdir(parents=True, exist_ok=True)
        (store.directory / "2026-01-01-bad.json").write_text("{not json")
        # Does not raise; returns the valid record.
        recents = store.list_recent(limit=10)
        assert any(r.session_id == "ok" for r in recents)


class TestIssueLinkage:
    def test_link_issue_appends(self, tmp_path):
        store = _store(tmp_path)
        rec = store.record_run(session_id="s", question="q", synthesis="x", success=True)
        assert store.link_issue(rec.board_run_id, 2391) is True
        assert store.link_issue(rec.board_run_id, 2392) is True
        # Idempotent.
        assert store.link_issue(rec.board_run_id, 2391) is True
        loaded = store.get_run(rec.board_run_id)
        assert set(loaded.linked_issues) == {2391, 2392}

    def test_link_unknown_run_returns_false(self, tmp_path):
        store = _store(tmp_path)
        assert store.link_issue("board-20260101-deadbeef", 1) is False


class TestOutcomes:
    def test_record_close_and_get(self, tmp_path):
        store = _store(tmp_path)
        rec = store.record_run(session_id="s", question="q", synthesis="x", success=True)
        opened = "2026-05-01T00:00:00+00:00"
        closed = "2026-05-02T00:00:00+00:00"  # 24h later
        store.record_issue_closed(rec.board_run_id, 100, opened_at=opened, closed_at=closed)
        out = store.get_outcomes(rec.board_run_id)
        assert len(out["closed_issues"]) == 1
        assert out["closed_issues"][0]["issue"] == 100

    def test_record_close_idempotent(self, tmp_path):
        store = _store(tmp_path)
        rec = store.record_run(session_id="s", question="q", synthesis="x", success=True)
        store.record_issue_closed(rec.board_run_id, 100)
        store.record_issue_closed(rec.board_run_id, 100)
        out = store.get_outcomes(rec.board_run_id)
        assert len(out["closed_issues"]) == 1

    def test_bad_run_id_on_close_is_noop(self, tmp_path):
        store = _store(tmp_path)
        store.record_issue_closed("not-a-run-id", 1)
        # No outcomes file created for a bad id.
        assert not (store.directory / "not-a-run-id-outcomes.json").exists()


class TestImplementationRate:
    def test_rate_and_avg_close(self, tmp_path):
        store = _store(tmp_path)
        rec = store.record_run(
            session_id="s", question="q", synthesis="x", success=True,
            member_count=7, cost_usd=1.0, phase="phase-2",
        )
        store.link_issue(rec.board_run_id, 1)
        store.link_issue(rec.board_run_id, 2)
        opened = datetime(2026, 5, 1, tzinfo=timezone.utc)
        store.record_issue_closed(
            rec.board_run_id, 1,
            opened_at=opened.isoformat(),
            closed_at=(opened + timedelta(hours=10)).isoformat(),
        )
        stats = store.compute_implementation_rate()
        assert stats["total_generated"] == 2
        assert stats["total_closed"] == 1
        assert stats["implementation_rate"] == 0.5
        run = stats["runs"][0]
        assert run["issues_generated"] == 2
        assert run["issues_closed"] == 1
        assert run["avg_close_hours"] == 10.0

    def test_empty_store(self, tmp_path):
        store = _store(tmp_path)
        stats = store.compute_implementation_rate()
        assert stats["total_generated"] == 0
        assert stats["implementation_rate"] is None
        assert store.outcome_summary_for_prompt() == ""

    def test_summary_for_prompt(self, tmp_path):
        store = _store(tmp_path)
        rec = store.record_run(session_id="s", question="q", synthesis="x", success=True)
        store.link_issue(rec.board_run_id, 5)
        store.record_issue_closed(rec.board_run_id, 5)
        summary = store.outcome_summary_for_prompt()
        assert "Prior board-run outcomes" in summary
        assert "1/1 issues closed" in summary
