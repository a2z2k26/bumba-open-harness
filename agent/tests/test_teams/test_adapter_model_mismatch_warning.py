"""Tests for the adapter ↔ model-prefix consistency warning (#1961) and the
strict-mode validator promotion (S2.4 #2339).

The runtime routes through OpenRouter based on ``spec.model`` prefix, not
on ``spec.adapter`` — so the 6 paradoxical ``adapter:"claude"`` +
``model:"openrouter:*"`` pairs across 6 department YAMLs (board, qa, design,
strategy, ops, job_search) actually work post-fix. The cost is that the
declared operator intent is contradictory.

These tests pin TWO surfaces:

1. The load-time WARNING in ``teams._config._warn_adapter_model_mismatch``
   that surfaces the contradiction in logs whenever a YAML is loaded.
   Preserved as advisory output for scaffolding (S2.4).
2. The validate-team-yaml ``--strict`` promotion: same mismatch becomes a
   blocking ERROR under ``--strict``, matching the ``delegation_floor``
   pattern (S2.4 #2339, 2026-05-19).
"""
from __future__ import annotations

import logging
import textwrap
from pathlib import Path

import pytest

from scripts.validate_team_yaml import validate_team
from teams._config import load_department_config


def _write_yaml(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "team.yaml"
    path.write_text(textwrap.dedent(body))
    return path


class TestAdapterModelMismatchWarning:
    def test_claude_adapter_with_openrouter_model_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = _write_yaml(
            tmp_path,
            """\
            team:
              name: test
              zone: 4
              chief:
                name: test-chief
                model: openrouter:openai/gpt-5
                adapter: claude
              workers:
                - name: test-worker
                  model: sonnet-4.6
                  adapter: claude
            """,
        )

        with caplog.at_level(logging.WARNING, logger="teams._config"):
            load_department_config(path)

        # The chief mismatch should be warned
        mismatch_records = [
            r for r in caplog.records
            if "adapter=claude" in r.getMessage()
            and "openrouter:" in r.getMessage()
        ]
        assert mismatch_records, (
            "expected a warning for chief with adapter=claude + "
            f"model=openrouter:* but got records: {[r.getMessage() for r in caplog.records]}"
        )

    def test_openrouter_adapter_with_non_openrouter_model_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = _write_yaml(
            tmp_path,
            """\
            team:
              name: test
              zone: 4
              chief:
                name: test-chief
                model: opus-4.6
                adapter: claude
              workers:
                - name: test-worker
                  model: sonnet-4.6
                  adapter: openrouter
            """,
        )

        with caplog.at_level(logging.WARNING, logger="teams._config"):
            load_department_config(path)

        mismatch_records = [
            r for r in caplog.records
            if "adapter=openrouter" in r.getMessage()
            and "lacks 'openrouter:'" in r.getMessage()
        ]
        assert mismatch_records, (
            "expected a warning for worker with adapter=openrouter + "
            "non-openrouter model"
        )

    def test_consistent_adapter_and_model_does_not_warn(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = _write_yaml(
            tmp_path,
            """\
            team:
              name: test
              zone: 4
              chief:
                name: test-chief
                model: opus-4.6
                adapter: claude
              workers:
                - name: test-claude-worker
                  model: sonnet-4.6
                  adapter: claude
                - name: test-openrouter-worker
                  model: openrouter:openai/gpt-5
                  adapter: openrouter
            """,
        )

        with caplog.at_level(logging.WARNING, logger="teams._config"):
            load_department_config(path)

        mismatch_records = [
            r for r in caplog.records
            if "adapter=" in r.getMessage()
            and ("starts with 'openrouter:'" in r.getMessage()
                 or "lacks 'openrouter:'" in r.getMessage())
        ]
        assert mismatch_records == [], (
            f"expected no adapter↔model mismatch warnings for consistent YAML, "
            f"got: {[r.getMessage() for r in mismatch_records]}"
        )

    def test_warning_includes_yaml_path_and_agent_name(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = _write_yaml(
            tmp_path,
            """\
            team:
              name: test
              zone: 4
              chief:
                name: my-special-chief
                model: openrouter:openai/gpt-5
                adapter: claude
              workers:
                - name: worker-1
                  model: sonnet-4.6
            """,
        )

        with caplog.at_level(logging.WARNING, logger="teams._config"):
            load_department_config(path)

        msgs = [r.getMessage() for r in caplog.records]
        # The warning text should name the offending chief
        assert any("my-special-chief" in m for m in msgs), (
            f"warning should name the offending agent, got: {msgs}"
        )


# ---------------------------------------------------------------------------
# S2.4 (#2339) — validator strict-mode promotion
# ---------------------------------------------------------------------------


def _write_full_team_yaml(tmp_path: Path, *, chief_adapter: str, chief_model: str) -> Path:
    """Write a YAML deliberately rigged with an adapter/model mismatch.

    Single-director shape (no workers) — keeps the fixture focused on the
    adapter/model check by sidestepping the delegation-floor strict rule.
    """
    path = tmp_path / "test_team.yaml"
    path.write_text(
        textwrap.dedent(
            f"""\
            team:
              name: test-mismatch
              zone: 4
              chief:
                name: test-chief
                model: {chief_model}
                adapter: {chief_adapter}
              workers: []
            """
        )
    )
    return path


class TestAdapterModelMismatchStrictMode:
    """S2.4 #2339 — strict mode promotes adapter/model mismatch to ERROR."""

    def test_strict_mode_fails_on_claude_adapter_openrouter_model(
        self, tmp_path: Path
    ) -> None:
        path = _write_full_team_yaml(
            tmp_path,
            chief_adapter="claude",
            chief_model="openrouter:openai/gpt-5",
        )

        report = validate_team(path, strict=True)

        assert not report.ok, (
            "expected --strict to FAIL on adapter=claude + model=openrouter:*"
        )
        assert any(
            "adapter_model_mismatch" in e for e in report.errors
        ), f"expected adapter_model_mismatch error, got: {report.errors}"

    def test_strict_mode_fails_on_openrouter_adapter_non_openrouter_model(
        self, tmp_path: Path
    ) -> None:
        path = _write_full_team_yaml(
            tmp_path,
            chief_adapter="openrouter",
            chief_model="opus-4.6",
        )

        report = validate_team(path, strict=True)

        assert not report.ok, (
            "expected --strict to FAIL on adapter=openrouter + non-openrouter model"
        )
        assert any(
            "adapter_model_mismatch" in e for e in report.errors
        ), f"expected adapter_model_mismatch error, got: {report.errors}"

    def test_non_strict_mode_keeps_mismatch_advisory(self, tmp_path: Path) -> None:
        """Back-compat: non-strict mode emits a WARN, not an ERROR — matches
        the load-time advisory behaviour, lets scaffolding workflows run."""
        path = _write_full_team_yaml(
            tmp_path,
            chief_adapter="claude",
            chief_model="openrouter:openai/gpt-5",
        )

        report = validate_team(path, strict=False)

        assert report.ok, (
            f"expected non-strict to PASS (warning only), got errors: {report.errors}"
        )
        assert any(
            "adapter_model_mismatch" in w for w in report.warnings
        ), f"expected adapter_model_mismatch warning, got: {report.warnings}"

    def test_strict_mode_passes_on_consistent_pair(self, tmp_path: Path) -> None:
        path = _write_full_team_yaml(
            tmp_path,
            chief_adapter="openrouter",
            chief_model="openrouter:openai/gpt-5",
        )

        report = validate_team(path, strict=True)

        # No adapter_model_mismatch surfaced — strict mode is silent on
        # consistent pairs (other strict rules may still bucket here, but
        # this YAML satisfies them all by construction).
        mismatch_errs = [e for e in report.errors if "adapter_model_mismatch" in e]
        mismatch_warns = [w for w in report.warnings if "adapter_model_mismatch" in w]
        assert mismatch_errs == [] and mismatch_warns == [], (
            f"expected no adapter_model_mismatch diagnostics, "
            f"got errors={mismatch_errs}, warnings={mismatch_warns}"
        )
