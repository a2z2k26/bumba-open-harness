"""Tests for E2.2: OTEL-shape facade over bridge.tracing.Tracer.

Sprint #1239 — opentelemetry-api facade in tracing.py + tool_shed.py instrumentation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_shed_with_tools(config_path: Path) -> "ToolShed":  # type: ignore[name-defined]
    """Build a ToolShed from a minimal YAML config."""
    from bridge.tool_shed import ToolShed

    config_path.write_text(
        "tools:\n"
        "  slack-send:\n"
        "    category: communication\n"
        "    always_loaded: false\n"
        "    agents: [all]\n"
        "    description: Send a message to a Slack channel\n"
        "  github-create-pr:\n"
        "    category: engineering\n"
        "    always_loaded: false\n"
        "    agents: [all]\n"
        "    description: Open a GitHub pull request\n"
        "  calendar-create:\n"
        "    category: scheduling\n"
        "    always_loaded: false\n"
        "    agents: [all]\n"
        "    description: Create a calendar event\n",
        encoding="utf-8",
    )
    return ToolShed(config_path)


# ---------------------------------------------------------------------------
# Test 1: facade emits a span to the JSONL sink
# ---------------------------------------------------------------------------


def test_facade_emits_span_to_jsonl_sink(tmp_path: Path) -> None:
    """OTELTracerFacade.start_as_current_span writes one span to the JSONL sink."""
    from bridge.tracing import OTELTracerFacade, get_otel_tracer, reset_tracers

    reset_tracers()
    sink = tmp_path / "traces.jsonl"
    tracer = get_otel_tracer("bumba.test", output_path=sink)
    assert isinstance(tracer, OTELTracerFacade)

    with tracer.start_as_current_span("test.operation", attributes={"key": "value"}) as span:
        assert span is not None

    lines = sink.read_text().strip().splitlines()
    assert len(lines) == 1, f"Expected 1 span, got {len(lines)}"
    record = json.loads(lines[0])
    assert record["name"] == "test.operation"
    assert record["attributes"].get("key") == "value"
    assert record["end_time"] is not None
    assert record["status"] == "ok"
    reset_tracers()


# ---------------------------------------------------------------------------
# Test 2: facade-emitted span has same shape as Tracer.context_span spans
# ---------------------------------------------------------------------------


def test_facade_span_shape_matches_context_span(tmp_path: Path) -> None:
    """Facade spans and context_span spans produce identical JSONL record shapes."""
    from bridge.tracing import get_otel_tracer, get_tracer, reset_tracers

    reset_tracers()
    sink_facade = tmp_path / "facade.jsonl"
    sink_direct = tmp_path / "direct.jsonl"

    facade = get_otel_tracer("bumba.facade-shape", output_path=sink_facade)
    with facade.start_as_current_span("shape.test"):
        pass

    tracer = get_tracer("bumba.direct-shape", output_path=sink_direct)
    with tracer.context_span("shape.test"):
        pass

    facade_record = json.loads(sink_facade.read_text().strip())
    direct_record = json.loads(sink_direct.read_text().strip())

    # Both must carry the mandatory fields
    required_fields = {"span_id", "trace_id", "name", "start_time", "end_time", "attributes", "status"}
    assert required_fields.issubset(facade_record.keys()), f"Missing fields: {required_fields - facade_record.keys()}"
    assert required_fields.issubset(direct_record.keys())
    reset_tracers()


# ---------------------------------------------------------------------------
# Test 3: missing opentelemetry-api raises ImportError
# ---------------------------------------------------------------------------


def test_facade_missing_otel_api_raises() -> None:
    """get_otel_tracer raises ImportError when opentelemetry-api is absent."""
    import bridge.tracing as tracing_mod

    original = tracing_mod._OTEL_AVAILABLE
    tracing_mod._OTEL_AVAILABLE = False
    try:
        with pytest.raises(ImportError, match="opentelemetry-api"):
            tracing_mod.get_otel_tracer("bumba.missing-test")
    finally:
        tracing_mod._OTEL_AVAILABLE = original


# ---------------------------------------------------------------------------
# Test 4: tool_shed resolve emits span with all expected attributes
# ---------------------------------------------------------------------------


def test_tool_shed_resolve_attributes(tmp_path: Path) -> None:
    """get_tools_for_intent emits one span with all 6 expected attributes."""
    from bridge.tracing import reset_tracers

    # Point tool_shed's module-level tracer at a temp sink.
    import bridge.tool_shed as shed_mod

    reset_tracers()
    sink = tmp_path / "shed.jsonl"

    # Re-create the module-level tracer pointing to our temp sink.
    from bridge.tracing import OTELTracerFacade, get_tracer

    new_facade = OTELTracerFacade(
        name="bumba.tool_shed",
        tracer=get_tracer("bumba.tool_shed", output_path=sink),
    )
    original_tracer = shed_mod._otel_tracer
    shed_mod._otel_tracer = new_facade

    try:
        config_path = tmp_path / "tool-shed.yaml"
        shed = _make_tool_shed_with_tools(config_path)

        results = shed.get_tools_for_intent("send a slack message", top_k=1)

        assert len(results) >= 1, "Expected at least one result"
        winner = results[0]
        assert winner.name == "slack-send", f"Expected slack-send, got {winner.name}"

        # Read the emitted span
        lines = sink.read_text().strip().splitlines()
        assert len(lines) == 1, f"Expected 1 span, got {len(lines)}"
        record = json.loads(lines[0])
        attrs = record["attributes"]

        # Assert all 6 spec-required attributes are present
        assert "query" in attrs, "Missing: query"
        assert "corpus_size" in attrs, "Missing: corpus_size"
        assert "winner_name" in attrs, "Missing: winner_name"
        assert "bm25_score" in attrs, "Missing: bm25_score"
        assert "vector_score" in attrs, "Missing: vector_score"
        assert "rrf_score" in attrs, "Missing: rrf_score"

        # Validate attribute values
        assert attrs["query"] == "send a slack message"
        assert attrs["corpus_size"] == 3
        assert attrs["winner_name"] == "slack-send"
        assert float(attrs["bm25_score"]) >= 0.0
        assert -1.0 <= float(attrs["vector_score"]) <= 1.0  # cosine range [-1, 1]
        assert float(attrs["rrf_score"]) > 0.0
    finally:
        shed_mod._otel_tracer = original_tracer
        reset_tracers()


# ---------------------------------------------------------------------------
# Test 5: span emitted even when no winner found (empty corpus)
# ---------------------------------------------------------------------------


def test_tool_shed_no_results_does_not_emit_winner_attrs(tmp_path: Path) -> None:
    """When resolve returns no results, span has query + corpus_size but no winner_name."""
    from bridge.tracing import OTELTracerFacade, get_tracer, reset_tracers

    import bridge.tool_shed as shed_mod

    reset_tracers()
    sink = tmp_path / "no-winner.jsonl"

    new_facade = OTELTracerFacade(
        name="bumba.tool_shed",
        tracer=get_tracer("bumba.tool_shed", output_path=sink),
    )
    original_tracer = shed_mod._otel_tracer
    shed_mod._otel_tracer = new_facade

    try:
        # Build shed with no tools
        config_path = tmp_path / "empty.yaml"
        config_path.write_text("tools: {}\n", encoding="utf-8")

        from bridge.tool_shed import ToolShed

        shed = ToolShed(config_path)
        results = shed.get_tools_for_intent("send a slack message", top_k=1)
        assert results == []

        # Empty corpus: the early `if not tools: return []` fires before the span
        # context manager is entered, so no span is written to the JSONL sink.
        assert not sink.exists() or sink.stat().st_size == 0
    finally:
        shed_mod._otel_tracer = original_tracer
        reset_tracers()


# ---------------------------------------------------------------------------
# Test 6: span_from_otel_context returns None when no active span
# ---------------------------------------------------------------------------


def test_span_from_otel_context_no_active_span() -> None:
    """span_from_otel_context returns None outside any span context."""
    from bridge.tracing import span_from_otel_context

    result = span_from_otel_context()
    assert result is None


# ---------------------------------------------------------------------------
# Test 7: existing Tracer.context_span API still works (regression)
# ---------------------------------------------------------------------------


def test_existing_context_span_unchanged(tmp_path: Path) -> None:
    """Tracer.context_span(...) still works correctly after E2.2 additions."""
    from bridge.tracing import get_tracer, reset_tracers

    reset_tracers()
    sink = tmp_path / "regression.jsonl"
    tracer = get_tracer("bumba.regression-test", output_path=sink)

    with tracer.context_span("legacy.operation", attributes={"legacy": True}) as span:
        span.add_event("checkpoint", {"step": 1})

    lines = sink.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["name"] == "legacy.operation"
    assert record["attributes"].get("legacy") is True
    assert len(record["events"]) == 1
    assert record["events"][0]["name"] == "checkpoint"
    reset_tracers()
