"""Tests for evidence_density_check.py."""

from __future__ import annotations

from pathlib import Path


# Import from scripts — ensure the scripts directory is on the path
import sys

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "scripts")
)

from evidence_density_check import (
    check_evidence,
    format_report,
    main,
    parse_sprint_ids,
)


# ---------------------------------------------------------------------------
# parse_sprint_ids
# ---------------------------------------------------------------------------

class TestParseSprintIds:
    """Sprint ID extraction from PR titles."""

    def test_single_sprint_dot(self) -> None:
        assert parse_sprint_ids("feat: Sprint 4.8 work") == ["4.8"]

    def test_single_sprint_hyphen(self) -> None:
        assert parse_sprint_ids("feat: sprint-4.8 work") == ["4.8"]

    def test_multiple_sprints(self) -> None:
        ids = parse_sprint_ids("feat: Sprint 4.8 + Sprint 4.9 changes")
        assert ids == ["4.8", "4.9"]

    def test_sprint_with_underscore_separator(self) -> None:
        assert parse_sprint_ids("sprint_4.8 update") == ["4.8"]

    def test_lowercase_sprint(self) -> None:
        assert parse_sprint_ids("feat: sprint 4.10 — new feature") == ["4.10"]

    def test_uppercase_sprint(self) -> None:
        assert parse_sprint_ids("Sprint 4.1 done") == ["4.1"]

    def test_two_digit_parts(self) -> None:
        assert parse_sprint_ids("sprint-04-09 follow-up") == ["04.09"]

    def test_no_sprint_ids(self) -> None:
        assert parse_sprint_ids("fix: typo in README") == []

    def test_duplicate_sprint_ids_deduped(self) -> None:
        ids = parse_sprint_ids("Sprint 4.8 and sprint-4.8 again")
        assert ids == ["4.8"]

    def test_hyphen_and_dot_normalize_same(self) -> None:
        ids = parse_sprint_ids("sprint-4-8 and Sprint 4.8")
        assert ids == ["4.8"]

    def test_sprint_in_parens(self) -> None:
        title = "feat(harness): Sprint 4.14 — tool trace reader (#245)"
        assert parse_sprint_ids(title) == ["4.14"]

    def test_multi_sprint_mixed_formats(self) -> None:
        title = "feat: Sprint 4.8, sprint-4.9, sprint_4.10 rollup"
        ids = parse_sprint_ids(title)
        assert ids == ["4.8", "4.9", "4.10"]

    def test_sprint_word_not_prefix(self) -> None:
        """'sprint' must appear as a prefix to the ID, not embedded."""
        assert parse_sprint_ids("this is not a sprint mention") == []

    def test_empty_title(self) -> None:
        assert parse_sprint_ids("") == []


# ---------------------------------------------------------------------------
# check_evidence
# ---------------------------------------------------------------------------

class TestCheckEvidence:
    """Evidence directory presence and file checks."""

    def test_all_present(self, tmp_path: Path) -> None:
        """Dirs exist with files -> all present, none missing."""
        for sid in ["4.8", "4.9"]:
            d = tmp_path / ".harness" / "evidence" / f"sprint-{sid}"
            d.mkdir(parents=True)
            (d / "pytest-output.txt").write_text("ok")

        present, missing = check_evidence(["4.8", "4.9"], tmp_path)
        assert present == ["4.8", "4.9"]
        assert missing == []

    def test_all_missing(self, tmp_path: Path) -> None:
        """No evidence dirs at all."""
        (tmp_path / ".harness" / "evidence").mkdir(parents=True)

        present, missing = check_evidence(["4.8", "4.9"], tmp_path)
        assert present == []
        assert missing == ["4.8", "4.9"]

    def test_partial_missing(self, tmp_path: Path) -> None:
        """One dir present, one missing."""
        d = tmp_path / ".harness" / "evidence" / "sprint-4.8"
        d.mkdir(parents=True)
        (d / "results.txt").write_text("pass")

        present, missing = check_evidence(["4.8", "4.9"], tmp_path)
        assert present == ["4.8"]
        assert missing == ["4.9"]

    def test_empty_dir_counts_as_missing(self, tmp_path: Path) -> None:
        """Dir exists but is empty -> treated as missing."""
        d = tmp_path / ".harness" / "evidence" / "sprint-4.8"
        d.mkdir(parents=True)

        present, missing = check_evidence(["4.8"], tmp_path)
        assert present == []
        assert missing == ["4.8"]

    def test_empty_sprint_list(self, tmp_path: Path) -> None:
        """No sprint IDs -> both lists empty."""
        present, missing = check_evidence([], tmp_path)
        assert present == []
        assert missing == []


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport:
    """Human-readable report formatting."""

    def test_no_sprint_ids(self) -> None:
        report = format_report([], [], [])
        assert "No sprint IDs found" in report
        assert "Skipping" in report

    def test_all_pass(self) -> None:
        report = format_report(["4.8", "4.9"], ["4.8", "4.9"], [])
        assert "PASS" in report
        assert "MISSING" not in report

    def test_missing_sprints(self) -> None:
        report = format_report(["4.8", "4.9"], ["4.8"], ["4.9"])
        assert "MISSING" in report
        assert "sprint-4.9" in report

    def test_all_missing(self) -> None:
        report = format_report(["4.8"], [], ["4.8"])
        assert "MISSING" in report
        assert "sprint-4.8" in report


# ---------------------------------------------------------------------------
# main (integration)
# ---------------------------------------------------------------------------

class TestMain:
    """End-to-end tests via the main() entry point."""

    def test_pass_with_evidence(self, tmp_path: Path) -> None:
        d = tmp_path / ".harness" / "evidence" / "sprint-4.8"
        d.mkdir(parents=True)
        (d / "output.txt").write_text("ok")

        rc = main(["feat: Sprint 4.8 done", str(tmp_path)])
        assert rc == 0

    def test_fail_missing_evidence(self, tmp_path: Path) -> None:
        (tmp_path / ".harness" / "evidence").mkdir(parents=True)

        rc = main(["feat: Sprint 4.8 done", str(tmp_path)])
        assert rc == 1

    def test_pass_non_sprint_pr(self, tmp_path: Path) -> None:
        rc = main(["fix: typo in README", str(tmp_path)])
        assert rc == 0

    def test_fail_partial_evidence(self, tmp_path: Path) -> None:
        d = tmp_path / ".harness" / "evidence" / "sprint-4.8"
        d.mkdir(parents=True)
        (d / "output.txt").write_text("ok")

        rc = main(["feat: Sprint 4.8 + Sprint 4.9", str(tmp_path)])
        assert rc == 1

    def test_pass_all_multiple(self, tmp_path: Path) -> None:
        for sid in ["4.8", "4.9", "4.10"]:
            d = tmp_path / ".harness" / "evidence" / f"sprint-{sid}"
            d.mkdir(parents=True)
            (d / "results.txt").write_text("pass")

        rc = main(["Sprint 4.8, Sprint 4.9, Sprint 4.10", str(tmp_path)])
        assert rc == 0

    def test_usage_error(self) -> None:
        rc = main([])
        assert rc == 2

    def test_usage_error_one_arg(self) -> None:
        rc = main(["just a title"])
        assert rc == 2

    def test_real_pr_title_format(self, tmp_path: Path) -> None:
        """Matches the actual PR title format used in this repo."""
        d = tmp_path / ".harness" / "evidence" / "sprint-4.14"
        d.mkdir(parents=True)
        (d / "pytest-output.txt").write_text("all passed")

        title = "feat(bridge): Sprint 4.14 — tool trace reader with secret redaction (#245)"
        rc = main([title, str(tmp_path)])
        assert rc == 0
