"""Tests for ``scripts/check_readiness_docs.py``.

Sprint R6.2 acceptance: stale-doc and undocumented-pending cases must
both be caught. Plus a live-tree integration test that fails if the
real readiness.sh + runbook drift apart on `main`.
"""
from __future__ import annotations

from pathlib import Path

from scripts.check_readiness_docs import (
    HarnessRows,
    RunbookRows,
    check,
    find_stale_backend_doc_patterns,
    main,
    parse_readiness_sh,
    parse_runbook,
    render_text,
)


# ---------------------------------------------------------------------------
# parse_readiness_sh
# ---------------------------------------------------------------------------


class TestParseReadinessSh:
    def test_extracts_run_check_rows(self):
        text = "\n".join([
            'run_check "make test" "offline pytest sweep" make test',
            'run_check "ruff check" "lint" ruff check agent/',
        ])
        rows = parse_readiness_sh(text)
        assert rows.live == {"make test", "ruff check"}
        assert rows.pending == set()

    def test_extracts_stub_pending_rows(self):
        text = 'stub_pending "halt: process-group" "PENDING: blocked by P1.2"'
        rows = parse_readiness_sh(text)
        assert rows.pending == {"halt: process-group"}
        assert rows.live == set()

    def test_extracts_record_row_pass_for_custom_blocks(self):
        """Custom subshell blocks emit `record_row "name" "PASS" ...` directly."""
        text = (
            '    record_row "services.runner --validate" "PASS"'
            ' "service registry validates" "$(tail ...)"'
        )
        rows = parse_readiness_sh(text)
        assert rows.live == {"services.runner --validate"}

    def test_extracts_record_row_fail_for_custom_blocks(self):
        text = (
            '    record_row "gitleaks detect" "FAIL"'
            ' "gitleaks binary not on PATH" "install via: brew install"'
        )
        rows = parse_readiness_sh(text)
        # FAIL still means the row exists.
        assert rows.live == {"gitleaks detect"}

    def test_filters_shell_variable_placeholders(self):
        """`record_row "${name}" ...` is the helper-fn definition, not a real row."""
        text = '    record_row "${name}" "PASS" "${note}" "${detail}"'
        rows = parse_readiness_sh(text)
        # Should NOT include the placeholder.
        assert rows.live == set()

    def test_returns_empty_for_irrelevant_text(self):
        rows = parse_readiness_sh("# nothing useful here\n")
        assert rows.live == set()
        assert rows.pending == set()


# ---------------------------------------------------------------------------
# parse_runbook
# ---------------------------------------------------------------------------


class TestParseRunbook:
    def test_extracts_live_rows_from_table(self):
        text = "\n".join([
            "## The N live checks",
            "",
            "| # | Row name | Command | Source |",
            "|---|----------|---------|--------|",
            "| 1 | `make test` | `make test` | offline pytest |",
            "| 2 | `ruff check` | `ruff check agent/` | lint |",
            "",
            "## Other section",
        ])
        rows = parse_runbook(text)
        assert rows.live == {"make test", "ruff check"}

    def test_extracts_pending_rows_active_and_retired(self):
        text = "\n".join([
            "## The PENDING rows",
            "",
            "| PENDING row | Blocker | Swap-in |",
            "|---|---|---|",
            "| ~~`halt: foo`~~ | ~~P1.2~~ | LIVE — see check #8 |",
            "| `still pending` | P9.9 | when shipped |",
            "",
            "## Other section",
        ])
        rows = parse_runbook(text)
        assert rows.pending_retired == {"halt: foo"}
        assert rows.pending_active == {"still pending"}

    def test_skips_unrelated_h2_sections(self):
        text = "\n".join([
            "## How to run",
            "",
            "| 1 | `not a check row` | spurious | spurious |",
            "",
            "## The N live checks",
            "",
            "| # | Row name | Command | Source |",
            "|---|----------|---------|--------|",
            "| 1 | `real check` | `cmd` | src |",
        ])
        rows = parse_runbook(text)
        assert rows.live == {"real check"}
        assert "not a check row" not in rows.live

    def test_returns_empty_for_no_sections(self):
        rows = parse_runbook("just prose, no tables\n")
        assert rows.live == set()
        assert rows.pending_active == set()
        assert rows.pending_retired == set()


# ---------------------------------------------------------------------------
# check — drift cases
# ---------------------------------------------------------------------------


class TestCheck:
    def test_clean_when_harness_and_runbook_agree(self):
        harness = HarnessRows(live={"a", "b"}, pending=set())
        runbook = RunbookRows(live={"a", "b"})
        result = check(harness, runbook)
        assert result.ok is True

    def test_stale_doc_pending_drift(self):
        """Runbook says PENDING but harness has live."""
        harness = HarnessRows(live={"halt-row"}, pending=set())
        runbook = RunbookRows(
            live={"halt-row"},  # also live in doc — both consistent
            pending_active={"halt-row"},  # but ALSO in pending — drift
        )
        result = check(harness, runbook)
        assert result.ok is False
        assert "halt-row" in result.stale_doc_pending

    def test_undocumented_pending_drift(self):
        """Harness has stub_pending but runbook lists neither active nor retired."""
        harness = HarnessRows(live=set(), pending={"new-pending"})
        runbook = RunbookRows()
        result = check(harness, runbook)
        assert result.ok is False
        assert "new-pending" in result.undocumented_pending

    def test_documented_retired_pending_does_not_drift(self):
        """Retired rows in the runbook satisfy the documentation rule."""
        harness = HarnessRows(live={"halt-row"}, pending=set())
        runbook = RunbookRows(
            live={"halt-row"},
            pending_retired={"halt-row"},  # retired marker — fine
        )
        result = check(harness, runbook)
        assert result.ok is True

    def test_undocumented_live_drift(self):
        """Harness has run_check but runbook live table doesn't list."""
        harness = HarnessRows(live={"new-row"}, pending=set())
        runbook = RunbookRows()
        result = check(harness, runbook)
        assert result.ok is False
        assert "new-row" in result.undocumented_live


# ---------------------------------------------------------------------------
# Backend doc drift — Sprint backend-op S5.2 (#2287)
# ---------------------------------------------------------------------------


class TestFindStaleBackendDocPatterns:
    """Drift checks for backend claims S5.1 brought into alignment."""

    def test_doc_drift_detects_legacy_warm_mcp_path(self, tmp_path):
        docs = tmp_path / "docs/current-state"
        docs.mkdir(parents=True)
        (docs / "README.md").write_text(
            "/opt/bumba-harness/agent-flat/agent/mcp-servers/bumba-memory/"
            "mcp-server.js\n"
            "feature_flags.yaml\n"  # satisfy the README requirement
        )
        failures = find_stale_backend_doc_patterns(tmp_path)
        assert failures
        assert any("legacy warm MCP path" in msg for msg in failures)

    def test_doc_drift_detects_legacy_warm_mcp_path_in_operator(
        self, tmp_path
    ):
        # The ban covers docs/operator too — operator runbooks must not
        # reintroduce the legacy warm-MCP path either.
        op_docs = tmp_path / "docs/operator"
        op_docs.mkdir(parents=True)
        (op_docs / "runbook.md").write_text(
            "agent-flat/agent/mcp-servers/bumba-memory/mcp-server.js\n"
        )
        # current-state/README required reference satisfied separately.
        cs = tmp_path / "docs/current-state"
        cs.mkdir(parents=True)
        (cs / "README.md").write_text("feature_flags.yaml\n")

        failures = find_stale_backend_doc_patterns(tmp_path)
        assert failures
        assert any("legacy warm MCP path" in msg for msg in failures)

    def test_doc_drift_allows_historical_8199_context(self, tmp_path):
        docs = tmp_path / "docs/current-state"
        docs.mkdir(parents=True)
        (docs / "README.md").write_text(
            "Historical stale 8199 references are not current.\n"
            "feature_flags.yaml\n"
        )
        assert find_stale_backend_doc_patterns(tmp_path) == []

    def test_doc_drift_detects_unqualified_8199(self, tmp_path):
        docs = tmp_path / "docs/current-state"
        docs.mkdir(parents=True)
        (docs / "README.md").write_text(
            "API runs on port 8199.\nfeature_flags.yaml\n"
        )
        failures = find_stale_backend_doc_patterns(tmp_path)
        assert any("unqualified legacy port 8199" in msg for msg in failures)

    def test_doc_drift_8199_qualifier_is_doc_wide(self, tmp_path):
        # "stale" anywhere in the doc — even far from the 8199 mention —
        # qualifies the reference. This matches the source-plan helper.
        docs = tmp_path / "docs/current-state"
        docs.mkdir(parents=True)
        (docs / "README.md").write_text(
            "Top of doc mentions stale claims policy.\n"
            "Middle: port 8199 used to be the bridge port.\n"
            "feature_flags.yaml\n"
        )
        assert find_stale_backend_doc_patterns(tmp_path) == []

    def test_doc_drift_8199_only_checked_in_current_state(self, tmp_path):
        # Operator docs can mention 8199 in release-notes context without
        # the stale/historical qualifier; only current-state is gated.
        op = tmp_path / "docs/operator"
        op.mkdir(parents=True)
        (op / "deploy.md").write_text("Bridge port flipped from 8199 to 8200.\n")
        cs = tmp_path / "docs/current-state"
        cs.mkdir(parents=True)
        (cs / "README.md").write_text("feature_flags.yaml\n")

        assert find_stale_backend_doc_patterns(tmp_path) == []

    def test_doc_drift_readme_must_mention_feature_flags_yaml(self, tmp_path):
        docs = tmp_path / "docs/current-state"
        docs.mkdir(parents=True)
        (docs / "README.md").write_text("Plain README with no marker.\n")
        failures = find_stale_backend_doc_patterns(tmp_path)
        assert any(
            "missing required reference to feature_flags.yaml" in msg
            for msg in failures
        )

    def test_doc_drift_empty_when_no_docs_dirs(self, tmp_path):
        # No docs/current-state, no docs/operator — nothing to gate.
        assert find_stale_backend_doc_patterns(tmp_path) == []

    def test_doc_drift_recurses_into_subdirs(self, tmp_path):
        # rglob covers nested operator sub-areas (audits, plans, …).
        nested = tmp_path / "docs/operator/nested-runbooks"
        nested.mkdir(parents=True)
        (nested / "old.md").write_text(
            "uses agent-flat/agent/mcp-servers/bumba-memory/mcp-server.js\n"
        )
        cs = tmp_path / "docs/current-state"
        cs.mkdir(parents=True)
        (cs / "README.md").write_text("feature_flags.yaml\n")

        failures = find_stale_backend_doc_patterns(tmp_path)
        assert any("legacy warm MCP path" in msg for msg in failures)


class TestLiveBackendDocDrift:
    """Run the drift check against the real repo tree.

    If this fails, a doc on `main` has reintroduced a stale claim
    (legacy port, legacy MCP path, missing feature_flags.yaml marker).
    """

    def test_repo_docs_are_drift_free(self):
        repo_root = Path(__file__).resolve().parent.parent.parent
        failures = find_stale_backend_doc_patterns(repo_root)
        assert failures == [], (
            "backend doc drift detected:\n  "
            + "\n  ".join(failures)
        )


# ---------------------------------------------------------------------------
# Live-tree integration — the high-confidence test the spec requires.
# ---------------------------------------------------------------------------


class TestLiveAgreement:
    """Run check() against the actual repo tree.

    If this test fails, either readiness.sh added/removed a row without
    updating the runbook, or the runbook drifted from the script.
    Either way the operator must see it before merge.
    """

    def test_readiness_sh_and_runbook_agree(self):
        repo_root = Path(__file__).resolve().parent.parent.parent
        sh = repo_root / "agent" / "scripts" / "readiness.sh"
        runbook = repo_root / "docs" / "operator" / "readiness-runbook.md"
        assert sh.is_file()
        assert runbook.is_file()
        harness = parse_readiness_sh(sh.read_text(encoding="utf-8"))
        runbook_rows = parse_runbook(runbook.read_text(encoding="utf-8"))
        result = check(harness, runbook_rows)
        # Surface specific drift in the assert message so the failure
        # is actionable from the test output alone.
        assert result.ok, (
            f"readiness docs drift detected:\n"
            f"  stale_doc_pending: {result.stale_doc_pending}\n"
            f"  undocumented_pending: {result.undocumented_pending}\n"
            f"  undocumented_live: {result.undocumented_live}"
        )


# ---------------------------------------------------------------------------
# CLI exit-code contract
# ---------------------------------------------------------------------------


class TestMain:
    def test_exit_zero_on_clean(self, tmp_path):
        sh = tmp_path / "readiness.sh"
        sh.write_text(
            'run_check "row a" "note" cmd\n'
            'run_check "row b" "note" cmd\n'
        )
        runbook = tmp_path / "runbook.md"
        runbook.write_text(
            "## The live checks\n\n"
            "| # | Row name | Command | Source |\n"
            "|---|---|---|---|\n"
            "| 1 | `row a` | cmd | n |\n"
            "| 2 | `row b` | cmd | n |\n"
        )
        rc = main(["--readiness-sh", str(sh), "--runbook", str(runbook)])
        assert rc == 0

    def test_exit_one_on_undocumented_live(self, tmp_path):
        sh = tmp_path / "readiness.sh"
        sh.write_text('run_check "row a" "note" cmd\n')
        runbook = tmp_path / "runbook.md"
        runbook.write_text("## live checks\n\n(no table)\n")
        rc = main(["--readiness-sh", str(sh), "--runbook", str(runbook)])
        assert rc == 1

    def test_exit_two_on_missing_readiness_sh(self, tmp_path):
        runbook = tmp_path / "runbook.md"
        runbook.write_text("# nothing\n")
        rc = main(
            ["--readiness-sh", str(tmp_path / "absent.sh"),
             "--runbook", str(runbook)]
        )
        assert rc == 2

    def test_exit_two_on_missing_runbook(self, tmp_path):
        sh = tmp_path / "readiness.sh"
        sh.write_text("# nothing\n")
        rc = main(
            ["--readiness-sh", str(sh),
             "--runbook", str(tmp_path / "absent.md")]
        )
        assert rc == 2

    def test_exit_one_on_backend_doc_drift(self, tmp_path):
        # Build a minimal fixture where harness/runbook agree but the
        # backend doc tree contains a banned legacy path. The CLI must
        # exit 1 even though the row-drift checks are clean.
        sh = tmp_path / "readiness.sh"
        sh.write_text(
            'run_check "row a" "note" cmd\n'
        )
        runbook = tmp_path / "runbook.md"
        runbook.write_text(
            "## The live checks\n\n"
            "| # | Row name | Command | Source |\n"
            "|---|---|---|---|\n"
            "| 1 | `row a` | cmd | n |\n"
        )
        # Plant the drift: legacy warm MCP path in current-state docs.
        docs = tmp_path / "docs/current-state"
        docs.mkdir(parents=True)
        (docs / "README.md").write_text(
            "agent-flat/agent/mcp-servers/bumba-memory/mcp-server.js\n"
            "feature_flags.yaml\n"
        )
        rc = main([
            "--readiness-sh", str(sh),
            "--runbook", str(runbook),
            "--repo-root", str(tmp_path),
        ])
        assert rc == 1


# ---------------------------------------------------------------------------
# render_text
# ---------------------------------------------------------------------------


class TestRenderText:
    def test_text_calls_out_each_drift_class(self):
        from scripts.check_readiness_docs import CheckResult

        result = CheckResult(
            harness=HarnessRows(live={"a"}, pending={"x"}),
            runbook=RunbookRows(live={"a"}, pending_active={"a"}),
            stale_doc_pending=["a"],
            undocumented_pending=["x"],
            undocumented_live=["b"],
            backend_doc_drift=["docs/current-state/foo.md: legacy warm MCP path"],
        )
        text = render_text(result)
        assert "STALE DOC PENDING" in text
        assert "UNDOCUMENTED PENDING" in text
        assert "UNDOCUMENTED LIVE" in text
        assert "BACKEND DOC DRIFT" in text

    def test_text_ok_marker_when_clean(self):
        from scripts.check_readiness_docs import CheckResult

        result = CheckResult()
        text = render_text(result)
        assert "OK — readiness docs agree" in text
