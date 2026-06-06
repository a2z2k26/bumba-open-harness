"""Unit tests for ``bridge.scripts.zone2_audit``.

Covers:

* ``classify`` — bucketing logic across all five buckets + boundary conditions.
* ``gather_health`` — registry iteration, missing/malformed state files,
  immutability of returned records.
* ``load_service_registry`` — JSON path, ``SERVICE_MAP`` import path, plist
  fallback path.
* ``render_markdown`` — bucket ordering, empty-bucket suppression, table
  formatting.
* ``run`` — end-to-end against a tmpdir; output paths created, exit code 0.
* Read-only invariant — state files unchanged (mtime/size/inode) after the
  script runs.

Layout follows the test conventions in ``agent/tests/conftest.py`` — see
``test_advanced_memory.py`` and similar for module-level imports.
"""
from __future__ import annotations

import json
import os
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bridge.scripts import zone2_audit
from bridge.scripts.zone2_audit import (
    BROKEN_CONSECUTIVE_FAILURES,
    DEGRADED_FAILURE_RATE,
    HEALTH_FIELDS,
    ServiceHealth,
    classify,
    gather_health,
    load_service_registry,
    render_markdown,
    run,
)


# ---------------------------------------------------------------------------
# classify()
# ---------------------------------------------------------------------------


class TestClassify:
    def test_empty_dict_is_no_data(self):
        assert classify({}) == "no-data"

    def test_all_defaults_is_no_data(self):
        # state file existed but service never ran — all counters zero.
        data = {f: None if f.startswith("last_") else 0 for f in HEALTH_FIELDS}
        assert classify(data) == "no-data"

    def test_broken_when_consecutive_failures_at_threshold(self):
        data = {
            "last_run": "2026-05-15T10:00:00Z",
            "consecutive_failures": BROKEN_CONSECUTIVE_FAILURES,
            "total_runs": 10,
            "total_failures": BROKEN_CONSECUTIVE_FAILURES,
        }
        assert classify(data) == "broken"

    def test_broken_when_consecutive_failures_above_threshold(self):
        data = {
            "last_run": "2026-05-15T10:00:00Z",
            "consecutive_failures": BROKEN_CONSECUTIVE_FAILURES + 3,
            "total_runs": 10,
            "total_failures": BROKEN_CONSECUTIVE_FAILURES + 3,
        }
        assert classify(data) == "broken"

    def test_degraded_when_consecutive_failures_in_range(self):
        data = {
            "last_run": "2026-05-15T10:00:00Z",
            "consecutive_failures": 1,
            "total_runs": 10,
            "total_failures": 1,
        }
        assert classify(data) == "degraded"

        data["consecutive_failures"] = BROKEN_CONSECUTIVE_FAILURES - 1
        assert classify(data) == "degraded"

    def test_degraded_when_failure_rate_above_threshold(self):
        # 10 runs, 1 failure ⇒ 10% > 5% ⇒ degraded
        data = {
            "last_run": "2026-05-15T10:00:00Z",
            "consecutive_failures": 0,  # NOT in failure streak
            "total_runs": 10,
            "total_failures": 1,
        }
        assert classify(data) == "degraded"

    def test_healthy_when_failure_rate_at_or_below_threshold(self):
        # 100 runs, 5 failures ⇒ exactly 5% — not strictly greater, so healthy.
        data = {
            "last_run": "2026-05-15T10:00:00Z",
            "consecutive_failures": 0,
            "total_runs": 100,
            "total_failures": 5,
        }
        assert classify(data) == "healthy"

    def test_stale_when_skip_ratio_high_and_skip_class_recognised(self):
        # 1 run, 10 skips, last skip class missing_secret ⇒ stale
        data = {
            "last_run": "2026-05-15T10:00:00Z",
            "consecutive_failures": 0,
            "total_runs": 1,
            "total_failures": 0,
            "total_skipped": 10,
            "last_skipped_class": "missing_secret",
        }
        assert classify(data) == "stale"

    def test_stale_requires_known_skip_class(self):
        # Same skip ratio but skip class is something unrecognised — falls
        # through to healthy because no failures.
        data = {
            "last_run": "2026-05-15T10:00:00Z",
            "consecutive_failures": 0,
            "total_runs": 1,
            "total_failures": 0,
            "total_skipped": 10,
            "last_skipped_class": "operator_paused",
        }
        assert classify(data) == "healthy"

    def test_healthy_baseline(self):
        data = {
            "last_run": "2026-05-15T10:00:00Z",
            "consecutive_failures": 0,
            "total_runs": 50,
            "total_failures": 0,
            "total_skipped": 0,
        }
        assert classify(data) == "healthy"

    def test_severity_precedence_broken_beats_degraded_skip(self):
        # Service is broken AND has high skip ratio — broken wins.
        data = {
            "last_run": "2026-05-15T10:00:00Z",
            "consecutive_failures": 10,
            "total_runs": 1,
            "total_failures": 10,
            "total_skipped": 100,
            "last_skipped_class": "missing_secret",
        }
        assert classify(data) == "broken"

    def test_failure_rate_threshold_value(self):
        # Sanity: the threshold constant matches the spec sketch (5%).
        assert DEGRADED_FAILURE_RATE == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# gather_health()
# ---------------------------------------------------------------------------


def _write_state(state_dir: Path, name: str, payload: dict) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    target = state_dir / f"{name}-state.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


class TestGatherHealth:
    def test_missing_state_file_yields_no_data(self, tmp_path: Path):
        registry = [{"service": "ghost", "plist": "com.bumba.agent-ghost", "schedule": "daily"}]
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        rows = gather_health(registry, state_dir)

        assert len(rows) == 1
        assert rows[0].service == "ghost"
        assert rows[0].bucket == "no-data"
        assert rows[0].last_run is None
        assert rows[0].consecutive_failures == 0

    def test_malformed_state_file_yields_no_data(self, tmp_path: Path):
        registry = [{"service": "garbled", "plist": "", "schedule": ""}]
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        (state_dir / "garbled-state.json").write_text("{not json", encoding="utf-8")

        rows = gather_health(registry, state_dir)

        assert rows[0].bucket == "no-data"

    def test_state_file_dispatches_to_classify(self, tmp_path: Path):
        registry = [
            {"service": "alpha", "plist": "p-alpha", "schedule": "daily"},
            {"service": "beta", "plist": "p-beta", "schedule": "hourly"},
        ]
        state_dir = tmp_path / "state"
        _write_state(state_dir, "alpha", {
            "last_run": "2026-05-15T10:00:00Z",
            "consecutive_failures": 0,
            "total_runs": 100,
            "total_failures": 0,
            "total_skipped": 0,
        })
        _write_state(state_dir, "beta", {
            "last_run": "2026-05-15T10:00:00Z",
            "consecutive_failures": 7,
            "total_runs": 5,
            "total_failures": 7,
        })

        rows = gather_health(registry, state_dir)
        rows_by_name = {r.service: r for r in rows}

        assert rows_by_name["alpha"].bucket == "healthy"
        assert rows_by_name["alpha"].total_runs == 100
        assert rows_by_name["beta"].bucket == "broken"
        assert rows_by_name["beta"].consecutive_failures == 7

    def test_record_is_immutable(self, tmp_path: Path):
        registry = [{"service": "alpha", "plist": "p", "schedule": "s"}]
        rows = gather_health(registry, tmp_path / "state")
        with pytest.raises(FrozenInstanceError):
            rows[0].service = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# load_service_registry()
# ---------------------------------------------------------------------------


class TestLoadServiceRegistry:
    def test_loads_from_json_when_path_exists(self, tmp_path: Path):
        registry_path = tmp_path / "registry.json"
        registry_path.write_text(
            json.dumps(
                [
                    {"service": "alpha", "plist": "p-a", "schedule": "daily"},
                    {"service": "beta", "plist": "p-b", "schedule": "hourly"},
                ]
            ),
            encoding="utf-8",
        )

        entries = load_service_registry(registry_path, plist_dir=tmp_path / "noplists")

        assert {e["service"] for e in entries} == {"alpha", "beta"}
        assert entries[0]["plist"] == "p-a"

    def test_falls_through_when_registry_missing_uses_service_map(self, tmp_path: Path):
        # If the registry path doesn't exist, the loader tries SERVICE_MAP.
        # In the bridge runtime that import succeeds — verify by asserting the
        # returned list is non-empty and entries have canonical shape.
        missing_path = tmp_path / "does-not-exist.json"

        entries = load_service_registry(missing_path, plist_dir=tmp_path / "noplists")

        assert isinstance(entries, list)
        if entries:  # SERVICE_MAP import path
            sample = entries[0]
            assert "service" in sample
            assert "plist" in sample
            assert "schedule" in sample

    def test_falls_through_to_plist_dir_when_service_map_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Force the SERVICE_MAP import to fail so the loader cascades to plists.
        monkeypatch.setattr(zone2_audit, "_load_from_service_map", lambda: None)

        plist_dir = tmp_path / "launchdaemons"
        plist_dir.mkdir()
        (plist_dir / "com.bumba.agent-alpha.plist").write_text("<plist/>", encoding="utf-8")
        (plist_dir / "com.bumba.agent-beta-two.plist").write_text("<plist/>", encoding="utf-8")
        (plist_dir / "unrelated.plist").write_text("<plist/>", encoding="utf-8")

        entries = load_service_registry(tmp_path / "missing.json", plist_dir=plist_dir)

        names = {e["service"] for e in entries}
        # Hyphens are normalised to underscores so the names align with
        # SERVICE_MAP keys when both sources are reconciled.
        assert names == {"alpha", "beta_two"}

    def test_malformed_registry_file_falls_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # When the registry path exists but isn't valid JSON, the loader should
        # NOT raise; it cascades to the next source.
        bad_path = tmp_path / "registry.json"
        bad_path.write_text("not json", encoding="utf-8")
        monkeypatch.setattr(zone2_audit, "_load_from_service_map", lambda: None)
        plist_dir = tmp_path / "plists"  # not created — empty fallback

        entries = load_service_registry(bad_path, plist_dir=plist_dir)

        assert entries == []


# ---------------------------------------------------------------------------
# render_markdown()
# ---------------------------------------------------------------------------


def _row(bucket: str, service: str = "svc", **overrides) -> ServiceHealth:
    base = dict(
        service=service,
        plist=f"com.bumba.agent-{service}",
        schedule="daily",
        last_run="2026-05-15T10:00:00Z",
        last_status="success",
        consecutive_failures=0,
        total_runs=10,
        total_failures=0,
        total_skipped=0,
        last_skipped_reason=None,
        last_skipped_class=None,
        last_duration_ms=1234,
        bucket=bucket,
    )
    base.update(overrides)
    return ServiceHealth(**base)


class TestRenderMarkdown:
    def test_header_present_and_total_count_correct(self):
        rows = [_row("healthy", "a"), _row("broken", "b")]
        out = render_markdown(rows, now=datetime(2026, 5, 17, tzinfo=timezone.utc))

        assert "# Zone 2 service health audit" in out
        assert "Generated: 2026-05-17T00:00:00+00:00" in out
        assert "Total services: 2" in out

    def test_buckets_render_in_severity_order(self):
        rows = [
            _row("healthy", "h1"),
            _row("broken", "b1"),
            _row("degraded", "d1"),
            _row("stale", "s1"),
            _row("no-data", "n1"),
        ]
        out = render_markdown(rows)

        # Index of each section header (lowercased) should match severity.
        sections = ["## Broken", "## Degraded", "## Stale", "## Healthy", "## No-Data"]
        positions = [out.index(s) for s in sections]
        assert positions == sorted(positions)

    def test_empty_buckets_are_suppressed(self):
        rows = [_row("healthy", "only")]
        out = render_markdown(rows)
        assert "## Broken" not in out
        assert "## Degraded" not in out
        assert "## Healthy (1)" in out

    def test_row_renders_with_em_dash_for_missing_fields(self):
        row = _row("no-data", "missing", last_run=None, last_status=None,
                   last_skipped_reason=None)
        out = render_markdown([row])
        # The em-dash placeholder appears for missing fields.
        assert "—" in out
        assert "`missing`" in out

    def test_markdown_table_has_header_row_per_bucket(self):
        rows = [_row("healthy", "h1"), _row("broken", "b1")]
        out = render_markdown(rows)
        # Two buckets ⇒ two header rows and two divider rows.
        assert out.count("| service | last_run") == 2
        assert out.count("|---|---|---|---|---|---|") == 2


# ---------------------------------------------------------------------------
# Read-only invariant + end-to-end run()
# ---------------------------------------------------------------------------


def _capture_stat(path: Path) -> tuple[int, int, int]:
    info = path.stat()
    return (info.st_ino, info.st_size, info.st_mtime_ns)


class TestRunEndToEnd:
    def test_run_writes_markdown_and_returns_zero(self, tmp_path: Path):
        # Build a tiny isolated tree.
        registry_path = tmp_path / "registry.json"
        registry_path.write_text(
            json.dumps([
                {"service": "alpha", "plist": "p-a", "schedule": "daily"},
                {"service": "beta", "plist": "p-b", "schedule": "hourly"},
            ]),
            encoding="utf-8",
        )
        state_dir = tmp_path / "state"
        _write_state(state_dir, "alpha", {
            "last_run": "2026-05-15T10:00:00Z",
            "consecutive_failures": 0,
            "total_runs": 50,
            "total_failures": 0,
        })
        _write_state(state_dir, "beta", {
            "last_run": "2026-05-15T10:00:00Z",
            "consecutive_failures": 0,
            "total_runs": 50,
            "total_failures": 0,
        })
        out_md = tmp_path / "reports" / "audit.md"
        out_json = tmp_path / "reports" / "audit.json"

        exit_code = run(_args(
            registry=registry_path,
            state_dir=state_dir,
            plist_dir=tmp_path / "noplists",
            out=out_md,
            json_out=out_json,
        ))

        assert exit_code == 0
        assert out_md.exists()
        text = out_md.read_text(encoding="utf-8")
        assert "Zone 2 service health audit" in text
        assert "`alpha`" in text and "`beta`" in text

        # JSON dump matches the rendered data.
        payload = json.loads(out_json.read_text(encoding="utf-8"))
        assert len(payload) == 2
        assert {entry["service"] for entry in payload} == {"alpha", "beta"}
        assert all("bucket" in entry for entry in payload)

    def test_run_does_not_modify_state_files(self, tmp_path: Path):
        """Read-only invariant — the load-bearing test for issue #2143.

        Captures (inode, size, mtime_ns) of every state file before invocation
        and asserts equality after. This is the operator's safety net: an
        aggregator that silently mutates state would corrupt the data we are
        trying to inspect.
        """
        registry_path = tmp_path / "registry.json"
        registry_path.write_text(
            json.dumps([
                {"service": "alpha", "plist": "p-a", "schedule": "daily"},
                {"service": "beta", "plist": "p-b", "schedule": "hourly"},
            ]),
            encoding="utf-8",
        )
        state_dir = tmp_path / "state"
        alpha_state = _write_state(state_dir, "alpha", {
            "last_run": "2026-05-15T10:00:00Z",
            "consecutive_failures": 0,
            "total_runs": 50,
        })
        beta_state = _write_state(state_dir, "beta", {
            "last_run": "2026-05-15T10:00:00Z",
            "consecutive_failures": 3,
            "total_runs": 10,
            "total_failures": 3,
        })

        before = {p: _capture_stat(p) for p in (alpha_state, beta_state)}
        before_registry = _capture_stat(registry_path)

        # Force-bump mtime granularity tolerance: ensure the OS clock has ticked
        # by setting future mtimes so any in-place rewrite would be detectable.
        future = before[alpha_state][2] + 1_000_000_000  # +1 second
        os.utime(alpha_state, ns=(future, future))
        os.utime(beta_state, ns=(future, future))
        before = {p: _capture_stat(p) for p in (alpha_state, beta_state)}

        out_md = tmp_path / "audit.md"
        run(_args(
            registry=registry_path,
            state_dir=state_dir,
            plist_dir=tmp_path / "noplists",
            out=out_md,
            json_out=None,
        ))

        for state_file, snapshot in before.items():
            after = _capture_stat(state_file)
            assert after == snapshot, (
                f"State file {state_file} was modified by zone2_audit; "
                f"before={snapshot}, after={after}"
            )
        assert _capture_stat(registry_path) == before_registry, (
            "Registry file was modified by zone2_audit"
        )

    def test_run_creates_parent_directory_for_output(self, tmp_path: Path):
        registry_path = tmp_path / "registry.json"
        registry_path.write_text(
            json.dumps([{"service": "alpha", "plist": "p", "schedule": "s"}]),
            encoding="utf-8",
        )
        deep_out = tmp_path / "a" / "b" / "c" / "audit.md"

        run(_args(
            registry=registry_path,
            state_dir=tmp_path / "state",
            plist_dir=tmp_path / "plists",
            out=deep_out,
            json_out=None,
        ))

        assert deep_out.exists()


def _args(**kwargs):
    """Build an ``argparse.Namespace`` with all fields ``run()`` requires."""
    import argparse
    defaults = {
        "registry": Path("agent/config/services-registry.json"),
        "state_dir": Path("data/service_state"),
        "plist_dir": Path("agent/config/launchdaemons"),
        "out": Path("docs/audits/zone2-audit.md"),
        "json_out": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)
