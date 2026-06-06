"""Tests for ``scripts/readiness_diff.py``.

Sprint R3.3 acceptance: cover PASS/PENDING/FAIL transitions, missing
rows, JSON output, and exit-code semantics. The tool is stdlib-only;
tests are also stdlib-only-by-policy (only ``pytest`` itself).
"""
from __future__ import annotations

import json

import pytest

from scripts.readiness_diff import (
    DiffResult,
    Row,
    diff_reports,
    main,
    parse_report,
    render_json,
    render_text,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _report(*rows: tuple[int, str, str, str]) -> str:
    """Build a minimal readiness report with the given rows.

    Each row is ``(index, name, status, notes)`` matching the
    production format in ``data/readiness-report.md``.
    """
    body = [
        "# Production Readiness Report",
        "",
        "- Generated: `2026-05-13T00:00:00Z`",
        "- Branch: `test` @ `deadbeef`",
        "- Strict mode: `0`",
        "- Overall: **PASS**",
        f"- Tally: {len(rows)} PASS / 0 FAIL / 0 PENDING",
        "",
        "## Checks",
        "",
        "| # | Check | Status | Notes |",
        "|---|-------|--------|-------|",
    ]
    for idx, name, status, notes in rows:
        body.append(f"| {idx} | {name} | {status} | {notes} |")
    body.append("")
    body.append("## Detail")
    body.append("")
    return "\n".join(body)


# ---------------------------------------------------------------------------
# parse_report
# ---------------------------------------------------------------------------


class TestParseReport:
    def test_parses_three_rows(self):
        text = _report(
            (1, "make test", "PASS", "offline pytest sweep"),
            (2, "ruff check", "PASS", "lint"),
            (3, "halt: process-group termination check", "PENDING", "blocked"),
        )
        rows = parse_report(text)
        assert len(rows) == 3
        assert rows[0] == Row(1, "make test", "PASS", "offline pytest sweep")
        assert rows[2].status == "PENDING"

    def test_skips_separator_and_header_rows(self):
        text = _report((1, "row", "PASS", "note"))
        rows = parse_report(text)
        # Exactly one data row — header + separator must not become rows.
        assert len(rows) == 1

    def test_stops_at_next_h2_section(self):
        # Manually craft a report where another H2 follows the table —
        # `## Detail` must not bleed into row parsing.
        text = "\n".join(
            [
                "## Checks",
                "",
                "| # | Check | Status | Notes |",
                "|---|-------|--------|-------|",
                "| 1 | a | PASS | n |",
                "",
                "## Detail",
                "",
                "| 99 | bogus | FAIL | should be ignored |",
            ]
        )
        rows = parse_report(text)
        assert len(rows) == 1
        assert rows[0].name == "a"

    def test_returns_empty_tuple_for_no_checks_section(self):
        rows = parse_report("# Nothing here\n\nJust prose.\n")
        assert rows == ()


# ---------------------------------------------------------------------------
# diff_reports — transitions
# ---------------------------------------------------------------------------


class TestTransitions:
    def test_pass_to_fail_is_regression(self):
        old = parse_report(_report((1, "row", "PASS", "n")))
        new = parse_report(_report((1, "row", "FAIL", "n")))
        result = diff_reports(old, new)

        assert len(result.regressions) == 1
        t = result.regressions[0]
        assert t.name == "row"
        assert t.old_status == "PASS"
        assert t.new_status == "FAIL"
        assert t.is_regression
        assert not t.is_improvement
        assert result.has_regressions

    def test_pass_to_pending_is_regression(self):
        old = parse_report(_report((1, "row", "PASS", "n")))
        new = parse_report(_report((1, "row", "PENDING", "n")))
        result = diff_reports(old, new)

        assert len(result.regressions) == 1
        assert result.regressions[0].new_status == "PENDING"
        assert result.has_regressions

    def test_pending_to_fail_is_regression(self):
        old = parse_report(_report((1, "row", "PENDING", "n")))
        new = parse_report(_report((1, "row", "FAIL", "n")))
        result = diff_reports(old, new)
        assert len(result.regressions) == 1

    def test_pending_to_pass_is_improvement(self):
        old = parse_report(_report((1, "row", "PENDING", "n")))
        new = parse_report(_report((1, "row", "PASS", "n")))
        result = diff_reports(old, new)

        assert len(result.improvements) == 1
        assert len(result.regressions) == 0
        assert not result.has_regressions
        t = result.improvements[0]
        assert t.is_improvement and not t.is_regression

    def test_fail_to_pass_is_improvement(self):
        old = parse_report(_report((1, "row", "FAIL", "n")))
        new = parse_report(_report((1, "row", "PASS", "n")))
        result = diff_reports(old, new)

        assert len(result.improvements) == 1
        assert not result.has_regressions

    def test_fail_to_pending_is_improvement(self):
        # FAIL → PENDING is an improvement at the severity level we use.
        old = parse_report(_report((1, "row", "FAIL", "n")))
        new = parse_report(_report((1, "row", "PENDING", "n")))
        result = diff_reports(old, new)
        assert len(result.improvements) == 1

    def test_unchanged_status_is_neither(self):
        old = parse_report(_report((1, "row", "PASS", "n")))
        new = parse_report(_report((1, "row", "PASS", "n")))
        result = diff_reports(old, new)
        assert len(result.unchanged) == 1
        assert len(result.transitions) == 0
        assert not result.has_regressions


# ---------------------------------------------------------------------------
# diff_reports — added / removed rows
# ---------------------------------------------------------------------------


class TestRowMembership:
    def test_added_row_is_not_regression(self):
        old = parse_report(_report((1, "a", "PASS", "n")))
        new = parse_report(
            _report((1, "a", "PASS", "n"), (2, "b", "PASS", "n"))
        )
        result = diff_reports(old, new)
        assert len(result.added_rows) == 1
        assert result.added_rows[0].name == "b"
        assert not result.has_regressions

    def test_removed_row_is_regression(self):
        old = parse_report(
            _report((1, "a", "PASS", "n"), (2, "b", "PASS", "n"))
        )
        new = parse_report(_report((1, "a", "PASS", "n")))
        result = diff_reports(old, new)
        assert len(result.removed_rows) == 1
        assert result.removed_rows[0].name == "b"
        assert result.has_regressions, (
            "removed row should be treated as a regression"
        )

    def test_renamed_row_shows_as_removed_plus_added(self):
        # A renamed row without an alias is a removal + an addition.
        # Removal still triggers regression — the diff tool guards
        # silent renames, the alias work belongs to a follow-up sprint.
        old = parse_report(_report((1, "old name", "PASS", "n")))
        new = parse_report(_report((1, "new name", "PASS", "n")))
        result = diff_reports(old, new)
        assert len(result.removed_rows) == 1
        assert len(result.added_rows) == 1
        assert result.has_regressions


# ---------------------------------------------------------------------------
# render_json
# ---------------------------------------------------------------------------


class TestRenderJson:
    def test_json_includes_summary_and_categories(self):
        old = parse_report(
            _report(
                (1, "stable", "PASS", "n"),
                (2, "regress", "PASS", "n"),
                (3, "improve", "PENDING", "n"),
                (4, "removed", "PASS", "n"),
            )
        )
        new = parse_report(
            _report(
                (1, "stable", "PASS", "n"),
                (2, "regress", "FAIL", "n"),
                (3, "improve", "PASS", "n"),
                (4, "added", "PASS", "n"),
            )
        )
        result = diff_reports(old, new)
        payload = json.loads(render_json(result))

        assert payload["summary"]["regressions"] == 1
        assert payload["summary"]["improvements"] == 1
        assert payload["summary"]["added_rows"] == 1
        assert payload["summary"]["removed_rows"] == 1
        assert payload["summary"]["unchanged"] == 1
        assert payload["summary"]["has_regressions"] is True

        assert payload["regressions"][0]["name"] == "regress"
        assert payload["regressions"][0]["new_status"] == "FAIL"
        assert payload["improvements"][0]["name"] == "improve"
        assert payload["added_rows"][0]["name"] == "added"
        assert payload["removed_rows"][0]["name"] == "removed"

    def test_json_clean_diff_has_no_regressions(self):
        old = parse_report(_report((1, "row", "PASS", "n")))
        new = parse_report(_report((1, "row", "PASS", "n")))
        payload = json.loads(render_json(diff_reports(old, new)))
        assert payload["summary"]["has_regressions"] is False
        assert payload["regressions"] == []


# ---------------------------------------------------------------------------
# render_text
# ---------------------------------------------------------------------------


class TestRenderText:
    def test_text_output_marks_regressions(self):
        old = parse_report(_report((1, "row", "PASS", "n")))
        new = parse_report(_report((1, "row", "FAIL", "n")))
        text = render_text(diff_reports(old, new))
        assert "REGRESSIONS" in text
        assert "row: PASS → FAIL" in text

    def test_text_output_marks_removed_row(self):
        old = parse_report(
            _report((1, "a", "PASS", "n"), (2, "b", "PASS", "n"))
        )
        new = parse_report(_report((1, "a", "PASS", "n")))
        text = render_text(diff_reports(old, new))
        assert "REMOVED ROWS" in text
        assert "b (was PASS)" in text


# ---------------------------------------------------------------------------
# main — exit code contract
# ---------------------------------------------------------------------------


class TestMain:
    def test_exit_zero_on_no_regression(self, tmp_path, capsys):
        old_path = tmp_path / "old.md"
        new_path = tmp_path / "new.md"
        old_path.write_text(_report((1, "row", "PENDING", "n")))
        new_path.write_text(_report((1, "row", "PASS", "n")))
        rc = main(["--old", str(old_path), "--new", str(new_path)])
        assert rc == 0
        captured = capsys.readouterr()
        assert "Improvements: 1" in captured.out

    def test_exit_one_on_regression(self, tmp_path, capsys):
        old_path = tmp_path / "old.md"
        new_path = tmp_path / "new.md"
        old_path.write_text(_report((1, "row", "PASS", "n")))
        new_path.write_text(_report((1, "row", "FAIL", "n")))
        rc = main(["--old", str(old_path), "--new", str(new_path)])
        assert rc == 1
        captured = capsys.readouterr()
        assert "REGRESSIONS" in captured.out

    def test_exit_one_on_removed_row(self, tmp_path):
        old_path = tmp_path / "old.md"
        new_path = tmp_path / "new.md"
        old_path.write_text(
            _report((1, "a", "PASS", "n"), (2, "b", "PASS", "n"))
        )
        new_path.write_text(_report((1, "a", "PASS", "n")))
        rc = main(["--old", str(old_path), "--new", str(new_path)])
        assert rc == 1

    def test_exit_two_when_old_missing(self, tmp_path, capsys):
        new_path = tmp_path / "new.md"
        new_path.write_text(_report((1, "a", "PASS", "n")))
        with pytest.raises(SystemExit) as excinfo:
            main(["--old", str(tmp_path / "absent.md"), "--new", str(new_path)])
        assert excinfo.value.code == 2

    def test_exit_two_when_report_has_no_rows(self, tmp_path):
        old_path = tmp_path / "old.md"
        new_path = tmp_path / "new.md"
        old_path.write_text("# nothing useful\n")
        new_path.write_text(_report((1, "a", "PASS", "n")))
        rc = main(["--old", str(old_path), "--new", str(new_path)])
        assert rc == 2

    def test_json_format_routes_through_main(self, tmp_path, capsys):
        old_path = tmp_path / "old.md"
        new_path = tmp_path / "new.md"
        old_path.write_text(_report((1, "row", "PASS", "n")))
        new_path.write_text(_report((1, "row", "FAIL", "n")))
        rc = main(
            [
                "--old",
                str(old_path),
                "--new",
                str(new_path),
                "--format",
                "json",
            ]
        )
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["summary"]["regressions"] == 1
        assert rc == 1


# ---------------------------------------------------------------------------
# DiffResult — invariants
# ---------------------------------------------------------------------------


class TestDiffResultInvariants:
    def test_empty_diff_has_no_regressions(self):
        result = DiffResult()
        assert not result.has_regressions
        assert result.regressions == ()
        assert result.improvements == ()
