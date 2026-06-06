"""Tests for workflow_id correlation on tracing Spans (sprint F-W.3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bridge.tracing import Span, Tracer, reset_tracers


@pytest.fixture(autouse=True)
def _reset_tracers() -> None:
    reset_tracers()


@pytest.fixture()
def tracer(tmp_path: Path) -> Tracer:
    return Tracer("test-service", output_path=tmp_path / "traces.jsonl")


class TestSpanWorkflowId:
    def test_workflow_id_default_none(self) -> None:
        span = Span(
            span_id="a",
            trace_id="b",
            parent_id=None,
            name="test",
            start_time=0.0,
        )
        assert span.workflow_id is None

    def test_to_dict_omits_none_workflow_id(self) -> None:
        span = Span(
            span_id="a",
            trace_id="b",
            parent_id=None,
            name="test",
            start_time=0.0,
        )
        d = span.to_dict()
        assert "workflow_id" not in d

    def test_to_dict_includes_workflow_id(self) -> None:
        span = Span(
            span_id="a",
            trace_id="b",
            parent_id=None,
            name="test",
            start_time=0.0,
            workflow_id="wf-run-123",
        )
        d = span.to_dict()
        assert d["workflow_id"] == "wf-run-123"


class TestTracerWorkflowIdPropagation:
    def test_start_span_sets_workflow_id(self, tracer: Tracer) -> None:
        span = tracer.start_span("root", workflow_id="wf-abc")
        assert span.workflow_id == "wf-abc"
        tracer.end_span(span)

    def test_child_inherits_workflow_id(self, tracer: Tracer) -> None:
        parent = tracer.start_span("parent", workflow_id="wf-abc")
        child = tracer.start_span("child")  # no explicit workflow_id
        assert child.workflow_id == "wf-abc"
        tracer.end_span(child)
        tracer.end_span(parent)

    def test_explicit_override_wins(self, tracer: Tracer) -> None:
        parent = tracer.start_span("parent", workflow_id="wf-abc")
        child = tracer.start_span("child", workflow_id="wf-xyz")
        assert child.workflow_id == "wf-xyz"
        tracer.end_span(child)
        tracer.end_span(parent)

    def test_no_workflow_id_when_not_set(self, tracer: Tracer) -> None:
        span = tracer.start_span("no-workflow")
        assert span.workflow_id is None
        tracer.end_span(span)

    def test_context_span_propagates(self, tracer: Tracer) -> None:
        with tracer.context_span("outer", workflow_id="wf-run-99") as outer:
            assert outer.workflow_id == "wf-run-99"
            with tracer.context_span("inner") as inner:
                assert inner.workflow_id == "wf-run-99"

    def test_parent_kwarg_inherits_workflow_id(self, tracer: Tracer) -> None:
        parent = tracer.start_span("parent", workflow_id="wf-parent")
        tracer.end_span(parent)
        child = tracer.start_span("child-sibling", parent=parent)
        assert child.workflow_id == "wf-parent"
        tracer.end_span(child)


class TestWorkflowIdInJSONL:
    def test_written_to_jsonl(self, tmp_path: Path) -> None:
        t = Tracer("svc", output_path=tmp_path / "t.jsonl")
        with t.context_span("step", workflow_id="wf-written"):
            pass
        lines = (tmp_path / "t.jsonl").read_text().strip().splitlines()
        assert lines
        d = json.loads(lines[-1])
        assert d.get("workflow_id") == "wf-written"

    def test_no_workflow_id_omitted_from_jsonl(self, tmp_path: Path) -> None:
        t = Tracer("svc", output_path=tmp_path / "t.jsonl")
        with t.context_span("step"):
            pass
        lines = (tmp_path / "t.jsonl").read_text().strip().splitlines()
        d = json.loads(lines[-1])
        assert "workflow_id" not in d


class TestGetRecentSpansWorkflowId:
    def test_roundtrip_workflow_id(self, tmp_path: Path) -> None:
        t = Tracer("svc", output_path=tmp_path / "t.jsonl")
        with t.context_span("step", workflow_id="wf-roundtrip"):
            pass
        spans = t.get_recent_spans(limit=5)
        assert spans
        assert spans[0].workflow_id == "wf-roundtrip"

    def test_none_workflow_id_roundtrip(self, tmp_path: Path) -> None:
        t = Tracer("svc", output_path=tmp_path / "t.jsonl")
        with t.context_span("step"):
            pass
        spans = t.get_recent_spans(limit=5)
        assert spans
        assert spans[0].workflow_id is None
