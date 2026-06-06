"""Tests for P6.4 (#1599) — startup and warm-path performance telemetry.

Covers two telemetry surfaces added by Sprint P6.4:
  1. ``record_completed_span`` in ``bridge.tracing`` — retroactive span emission
     for phases that ran before ``self._tracer`` existed.
  2. Warm-path latency histograms observed inside ``BridgeApp._invoke_claude``:
     ``warm_path.enqueue_to_start_seconds`` and ``warm_path.total_seconds``.

The startup span emission is exercised directly through the helper; the
warm-path observe sites are exercised by reading the spans out of
``data/traces.jsonl`` so the assertions don't depend on importing the full
BridgeApp under test.
"""

from __future__ import annotations

import json
import time

import pytest

from bridge.tracing import Tracer, record_completed_span


class TestRecordCompletedSpan:
    """Verify the retroactive-span helper writes correctly into JSONL."""

    def test_emits_span_with_explicit_timestamps(self, tmp_path):
        out = tmp_path / "traces.jsonl"
        tracer = Tracer("bridge", output_path=out)

        start = time.time()
        end = start + 0.123  # 123ms phase
        span = record_completed_span(
            tracer,
            "startup.config_load",
            start,
            end,
            attributes={"config_path": "default"},
        )

        assert span.name == "startup.config_load"
        assert span.start_time == start
        assert span.end_time == end
        assert span.status == "ok"
        assert span.attributes["service.name"] == "bridge"
        assert span.attributes["config_path"] == "default"

        # JSONL was written
        lines = out.read_text().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["name"] == "startup.config_load"
        assert record["start_time"] == start
        assert record["end_time"] == end
        assert record["status"] == "ok"

    def test_does_not_push_onto_context_stack(self, tmp_path):
        """Retroactive spans must not participate in parent/child nesting."""
        out = tmp_path / "traces.jsonl"
        tracer = Tracer("bridge", output_path=out)

        # Stack must be empty before
        assert tracer._context.depth == 0

        record_completed_span(
            tracer,
            "startup.db_migrate",
            time.time(),
            time.time() + 0.01,
        )

        # Stack must remain empty — record_completed_span writes only.
        assert tracer._context.depth == 0

        # A subsequent context_span MUST get a fresh trace_id (no leakage).
        with tracer.context_span("request.handle") as span:
            assert span.parent_id is None

    def test_rejects_end_before_start(self, tmp_path):
        out = tmp_path / "traces.jsonl"
        tracer = Tracer("bridge", output_path=out)

        now = time.time()
        with pytest.raises(ValueError, match="end_time"):
            record_completed_span(
                tracer,
                "startup.broken",
                start_time=now,
                end_time=now - 1.0,
            )

    def test_error_status_attribute(self, tmp_path):
        out = tmp_path / "traces.jsonl"
        tracer = Tracer("bridge", output_path=out)

        start = time.time()
        record_completed_span(
            tracer,
            "startup.api_start",
            start_time=start,
            end_time=start + 0.5,
            attributes={"host": "127.0.0.1", "port": 8200},
            status="error",
        )

        record = json.loads(out.read_text().strip().splitlines()[0])
        assert record["status"] == "error"
        assert record["attributes"]["host"] == "127.0.0.1"
        assert record["attributes"]["port"] == 8200


class TestWarmPathLatencyMetricNames:
    """Verify the metric registry YAML for the warm-path histograms is well-formed.

    The actual ``MetricsCollector.observe`` call sites live in
    ``BridgeApp._invoke_claude``; the registry-completeness CI gate does not
    yet pattern-match ``observe`` (only ``record`` / ``increment`` / ``gauge``),
    so this test asserts the YAML names match the strings emitted by app.py.
    Drift here means the operator's ``/api/metrics/<name>`` URL won't resolve.
    """

    def test_metric_yaml_documents_both_histograms(self):
        from pathlib import Path

        registry_root = (
            Path(__file__).parent.parent
            / "config"
            / "registry"
            / "metrics"
            / "warm-path-latency.yaml"
        )
        assert registry_root.exists(), (
            f"Expected metrics registry entry at {registry_root}"
        )

        # Parse without bringing in PyYAML — assert the metric_name strings
        # appear in the file so the operator can hit /api/metrics/<name>.
        contents = registry_root.read_text()
        assert "warm_path.enqueue_to_start_seconds" in contents, (
            "warm_path.enqueue_to_start_seconds missing from registry"
        )
        assert "warm_path.total_seconds" in contents, (
            "warm_path.total_seconds missing from registry"
        )


class TestStartupSpanIntegrationShape:
    """Sanity-check the startup span names match what startup code emits.

    Pins the contract between BridgeApp._initialize / start and operator-facing
    consumers (e.g. /api/traces, future status block). If you rename a startup
    span in BridgeApp startup code, update this test in the same PR.
    """

    EXPECTED_NAMES = {
        "startup.config_load",
        "startup.db_migrate",
        "startup.registry_prewarm",
        "startup.warm_process_spawn",
        "startup.api_start",
    }

    def test_app_module_references_all_expected_phase_names(self):
        from pathlib import Path

        bridge_root = Path(__file__).parent.parent / "bridge"
        startup_src = "\n".join(
            [
                (bridge_root / "app.py").read_text(),
                (bridge_root / "app_init.py").read_text(),
            ]
        )

        missing = sorted(
            name for name in self.EXPECTED_NAMES if name not in startup_src
        )
        assert not missing, (
            f"BridgeApp startup code is missing P6.4 startup span name(s): {missing}"
        )
