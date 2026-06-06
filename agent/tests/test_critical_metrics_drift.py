"""Tests for ``agent/scripts/check_critical_metrics_drift.py``.

Sprint audit-2026-05-16.F.01 — covers the metrics-side drift gate for
finding SW-1. Three acceptance tests:

1. Synthetic registry containing every ``CRITICAL_METRICS`` member passes.
2. Synthetic registry missing one member fails with the missing name
   surfaced in the rendered output.
3. The real ``agent/config/registry/metrics/`` directory currently
   declares every member of ``CRITICAL_METRICS``. If this fails, the
   fix is to register the missing metric — never to weaken
   ``CRITICAL_METRICS``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.check_critical_metrics_drift import (
    CRITICAL_METRICS,
    CheckResult,
    _REGISTRY_METRICS_DIR,
    check,
    load_registered_metric_names,
    main,
    render_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_metric_yaml(
    target_dir: Path, filename: str, entries: dict[str, dict[str, str]]
) -> Path:
    """Write a registry-style YAML file with the given entries."""
    path = target_dir / filename
    path.write_text(yaml.safe_dump(entries, sort_keys=False), encoding="utf-8")
    return path


def _entry(metric_name: str) -> dict[str, str]:
    """Minimum-shape entry the loader accepts."""
    return {
        "kind": "metric",
        "name": metric_name.replace(".", " ").title(),
        "category": "Test",
        "description": f"Synthetic entry for {metric_name}.",
        "source_module": "tests.synthetic",
        "schema_ref": "int",
        "metric_name": metric_name,
        "access_method": "pull:/api/metrics/{name}",
    }


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


class TestCheckerPassesWhenAllCriticalRegistered:
    """Synthetic registry covers every critical metric => exit 0."""

    def test_checker_passes_when_all_critical_registered(self, tmp_path: Path):
        entries = {
            f"entry_{i}": _entry(name)
            for i, name in enumerate(sorted(CRITICAL_METRICS))
        }
        _write_metric_yaml(tmp_path, "autonomous-surfaces.yaml", entries)

        result = check(tmp_path)

        assert isinstance(result, CheckResult)
        assert result.ok is True
        assert result.missing == ()
        assert CRITICAL_METRICS.issubset(result.registered)

    def test_main_returns_zero_when_passing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        entries = {
            f"entry_{i}": _entry(name)
            for i, name in enumerate(sorted(CRITICAL_METRICS))
        }
        _write_metric_yaml(tmp_path, "autonomous-surfaces.yaml", entries)

        rc = main(["--metrics-dir", str(tmp_path)])

        assert rc == 0
        captured = capsys.readouterr()
        assert "OK" in captured.out
        assert captured.err == ""


class TestCheckerFailsOnSeededMissingMetric:
    """Synthetic registry missing one critical metric => exit 1, name surfaced."""

    def test_check_reports_missing_metric(self, tmp_path: Path):
        # Drop one critical metric — keep all the others.
        sorted_metrics = sorted(CRITICAL_METRICS)
        dropped = sorted_metrics[0]
        kept = sorted_metrics[1:]
        entries = {f"entry_{i}": _entry(name) for i, name in enumerate(kept)}
        _write_metric_yaml(tmp_path, "autonomous-surfaces.yaml", entries)

        result = check(tmp_path)

        assert result.ok is False
        assert dropped in result.missing
        assert len(result.missing) == 1

    def test_main_returns_nonzero_and_names_missing_metric(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        sorted_metrics = sorted(CRITICAL_METRICS)
        dropped = sorted_metrics[0]
        kept = sorted_metrics[1:]
        entries = {f"entry_{i}": _entry(name) for i, name in enumerate(kept)}
        _write_metric_yaml(tmp_path, "autonomous-surfaces.yaml", entries)

        rc = main(["--metrics-dir", str(tmp_path)])

        assert rc == 1
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        # The missing metric name MUST appear in the output so the operator
        # can act on the gate failure without rerunning anything.
        assert dropped in combined
        assert "MISSING CRITICAL METRICS" in combined

    def test_render_text_includes_suggested_file(self):
        result = CheckResult(
            registered=frozenset(),
            missing=("experiment.iteration.started",),
        )
        text = render_text(result)
        assert "experiment.iteration.started" in text
        # The render should hint where the operator can add the metric.
        assert "autonomous-surfaces.yaml" in text


class TestCheckerValidatesCurrentRepoState:
    """The real registry must declare every critical metric. If this fails,
    REGISTER the missing metric — do not weaken CRITICAL_METRICS."""

    def test_real_registry_declares_every_critical_metric(self):
        if not _REGISTRY_METRICS_DIR.is_dir():
            pytest.skip(
                f"metrics registry dir absent in this checkout: "
                f"{_REGISTRY_METRICS_DIR}"
            )
        registered = load_registered_metric_names(_REGISTRY_METRICS_DIR)
        missing = sorted(CRITICAL_METRICS - registered)
        assert not missing, (
            "Critical metrics missing from registry: "
            f"{missing}. Add an entry to "
            "agent/config/registry/metrics/autonomous-surfaces.yaml "
            "for each missing name."
        )

    def test_real_checker_exits_clean(self, capsys: pytest.CaptureFixture[str]):
        if not _REGISTRY_METRICS_DIR.is_dir():
            pytest.skip(
                f"metrics registry dir absent in this checkout: "
                f"{_REGISTRY_METRICS_DIR}"
            )
        rc = main(["--metrics-dir", str(_REGISTRY_METRICS_DIR)])
        assert rc == 0


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestCheckerErrors:
    def test_missing_directory_returns_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        missing_dir = tmp_path / "does-not-exist"
        rc = main(["--metrics-dir", str(missing_dir)])
        assert rc == 2
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_empty_directory_reports_all_critical_missing(self, tmp_path: Path):
        result = check(tmp_path)
        assert result.ok is False
        assert frozenset(result.missing) == CRITICAL_METRICS

    def test_yaml_entries_without_metric_name_are_skipped(self, tmp_path: Path):
        # An entry that lacks ``metric_name`` should be ignored — the
        # gate only contracts on metric_name strings.
        _write_metric_yaml(
            tmp_path,
            "stale.yaml",
            {"orphan": {"kind": "metric", "name": "Orphan"}},
        )
        names = load_registered_metric_names(tmp_path)
        assert names == frozenset()
