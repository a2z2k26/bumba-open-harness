"""Tests for bridge.tracing — lightweight OTEL-style tracing."""

from __future__ import annotations

import json
import threading
import time

import pytest

from bridge.tracing import (
    Span,
    SpanContext,
    Tracer,
    format_span_tree,
    generate_span_id,
    generate_trace_id,
    get_tracer,
    reset_tracers,
)


# ---------------------------------------------------------------------------
# TestSpanGeneration
# ---------------------------------------------------------------------------


class TestSpanGeneration:
    """Test that generated IDs are correct length and unique."""

    def test_trace_id_length(self):
        tid = generate_trace_id()
        # 16 bytes = 32 hex chars
        assert len(tid) == 32

    def test_trace_id_is_hex(self):
        tid = generate_trace_id()
        int(tid, 16)  # should not raise

    def test_span_id_length(self):
        sid = generate_span_id()
        # 8 bytes = 16 hex chars
        assert len(sid) == 16

    def test_span_id_is_hex(self):
        sid = generate_span_id()
        int(sid, 16)  # should not raise

    def test_ids_are_unique(self):
        trace_ids = {generate_trace_id() for _ in range(100)}
        assert len(trace_ids) == 100
        span_ids = {generate_span_id() for _ in range(100)}
        assert len(span_ids) == 100


# ---------------------------------------------------------------------------
# TestTracer
# ---------------------------------------------------------------------------


class TestTracer:
    """Test Tracer start/end span and context_span."""

    def test_start_end_span_writes_jsonl(self, tmp_path):
        out = tmp_path / "traces.jsonl"
        tracer = Tracer("test-svc", output_path=out)

        span = tracer.start_span("my.operation", attributes={"key": "val"})
        assert span.end_time is None
        assert span.status == "ok"

        tracer.end_span(span)
        assert span.end_time is not None
        assert span.end_time >= span.start_time

        # Verify JSONL was written
        lines = out.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["name"] == "my.operation"
        assert data["status"] == "ok"
        assert data["attributes"]["key"] == "val"
        assert data["attributes"]["service.name"] == "test-svc"
        assert data["span_id"] == span.span_id
        assert data["trace_id"] == span.trace_id
        assert data["parent_id"] is None

    def test_nested_spans_share_trace_id(self, tmp_path):
        out = tmp_path / "traces.jsonl"
        tracer = Tracer("test-svc", output_path=out)

        parent = tracer.start_span("parent")
        child = tracer.start_span("child")

        assert child.trace_id == parent.trace_id
        assert child.parent_id == parent.span_id

        tracer.end_span(child)
        tracer.end_span(parent)

        lines = out.read_text().strip().splitlines()
        assert len(lines) == 2

    def test_context_span_normal(self, tmp_path):
        out = tmp_path / "traces.jsonl"
        tracer = Tracer("test-svc", output_path=out)

        with tracer.context_span("ctx.op") as span:
            assert span.status == "ok"
            span.add_event("checkpoint", {"step": 1})

        # Span should be ended and written
        assert span.end_time is not None
        assert span.status == "ok"
        lines = out.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["status"] == "ok"
        assert len(data["events"]) == 1
        assert data["events"][0]["name"] == "checkpoint"

    def test_context_span_exception_marks_error(self, tmp_path):
        out = tmp_path / "traces.jsonl"
        tracer = Tracer("test-svc", output_path=out)

        with pytest.raises(ValueError, match="boom"):
            with tracer.context_span("failing.op") as span:
                raise ValueError("boom")

        assert span.status == "error"
        assert span.end_time is not None

        lines = out.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["status"] == "error"
        assert len(data["events"]) == 1
        assert data["events"][0]["name"] == "exception"
        assert data["events"][0]["attributes"]["exception.type"] == "ValueError"
        assert data["events"][0]["attributes"]["exception.message"] == "boom"

    def test_explicit_parent_overrides_context(self, tmp_path):
        out = tmp_path / "traces.jsonl"
        tracer = Tracer("test-svc", output_path=out)

        root = tracer.start_span("root")
        tracer.end_span(root)

        # Start a new span with explicit parent (not from context stack)
        explicit_parent = Span(
            span_id="deadbeef01234567",
            trace_id="aabb" * 8,
            parent_id=None,
            name="explicit",
            start_time=time.time(),
        )
        child = tracer.start_span("child", parent=explicit_parent)
        assert child.parent_id == "deadbeef01234567"
        assert child.trace_id == "aabb" * 8
        tracer.end_span(child)


# ---------------------------------------------------------------------------
# TestSpanContext
# ---------------------------------------------------------------------------


class TestSpanContext:
    """Test SpanContext parent stacking and thread isolation."""

    def test_push_pop_stack(self):
        ctx = SpanContext()
        s1 = Span(
            span_id="s1", trace_id="t1", parent_id=None,
            name="span1", start_time=time.time(),
        )
        s2 = Span(
            span_id="s2", trace_id="t1", parent_id="s1",
            name="span2", start_time=time.time(),
        )

        assert ctx.current_span is None
        assert ctx.depth == 0

        ctx.push(s1)
        assert ctx.current_span is s1
        assert ctx.trace_id == "t1"
        assert ctx.depth == 1

        ctx.push(s2)
        assert ctx.current_span is s2
        assert ctx.depth == 2

        popped = ctx.pop()
        assert popped is s2
        assert ctx.current_span is s1
        assert ctx.depth == 1

        popped = ctx.pop()
        assert popped is s1
        assert ctx.current_span is None
        assert ctx.trace_id is None
        assert ctx.depth == 0

    def test_pop_empty_returns_none(self):
        ctx = SpanContext()
        assert ctx.pop() is None

    def test_thread_isolation(self):
        ctx = SpanContext()
        results: dict[str, Span | None] = {}
        barrier = threading.Barrier(2)

        def thread_a():
            s = Span(
                span_id="a1", trace_id="ta", parent_id=None,
                name="thread_a_span", start_time=time.time(),
            )
            ctx.push(s)
            barrier.wait()  # sync with thread_b
            results["a"] = ctx.current_span
            ctx.pop()

        def thread_b():
            barrier.wait()  # wait for thread_a to push
            results["b"] = ctx.current_span  # should be None (isolated)

        ta = threading.Thread(target=thread_a)
        tb = threading.Thread(target=thread_b)
        ta.start()
        tb.start()
        ta.join()
        tb.join()

        assert results["a"] is not None
        assert results["a"].span_id == "a1"
        assert results["b"] is None  # thread_b sees its own empty context


# ---------------------------------------------------------------------------
# TestFormatSpanTree
# ---------------------------------------------------------------------------


class TestFormatSpanTree:
    """Test format_span_tree display output."""

    def test_empty_list(self):
        assert format_span_tree([]) == ""

    def test_single_span(self):
        span = Span(
            span_id="s1", trace_id="t1", parent_id=None,
            name="root.op", start_time=1000.0, end_time=1000.005,
        )
        result = format_span_tree([span])
        assert "[5.00ms] root.op (ok)" in result

    def test_nested_spans(self):
        root = Span(
            span_id="s1", trace_id="t1", parent_id=None,
            name="request", start_time=1000.0, end_time=1000.010,
        )
        child1 = Span(
            span_id="s2", trace_id="t1", parent_id="s1",
            name="db.query", start_time=1000.001, end_time=1000.005,
        )
        child2 = Span(
            span_id="s3", trace_id="t1", parent_id="s1",
            name="render", start_time=1000.006, end_time=1000.009,
        )
        grandchild = Span(
            span_id="s4", trace_id="t1", parent_id="s2",
            name="db.connect", start_time=1000.001, end_time=1000.002,
        )

        result = format_span_tree([root, child1, child2, grandchild])
        lines = result.splitlines()

        # Root at depth 0
        assert lines[0].startswith("[")
        assert "request" in lines[0]

        # Children at depth 1
        assert lines[1].startswith("  [")
        assert "db.query" in lines[1]

        # Grandchild at depth 2
        assert lines[2].startswith("    [")
        assert "db.connect" in lines[2]

        # Second child after grandchild subtree
        assert lines[3].startswith("  [")
        assert "render" in lines[3]

    def test_running_span(self):
        span = Span(
            span_id="s1", trace_id="t1", parent_id=None,
            name="ongoing", start_time=1000.0, end_time=None,
        )
        result = format_span_tree([span])
        assert "[running] ongoing (ok)" in result

    def test_error_status_displayed(self):
        span = Span(
            span_id="s1", trace_id="t1", parent_id=None,
            name="fail.op", start_time=1000.0, end_time=1000.003,
            status="error",
        )
        result = format_span_tree([span])
        assert "(error)" in result


# ---------------------------------------------------------------------------
# TestTracerSingleton
# ---------------------------------------------------------------------------


class TestTracerSingleton:
    """Test get_tracer singleton behavior."""

    def setup_method(self):
        reset_tracers()

    def teardown_method(self):
        reset_tracers()

    def test_same_instance_returned(self):
        t1 = get_tracer("my-service")
        t2 = get_tracer("my-service")
        assert t1 is t2

    def test_different_services_different_instances(self):
        t1 = get_tracer("service-a")
        t2 = get_tracer("service-b")
        assert t1 is not t2
        assert t1.service_name == "service-a"
        assert t2.service_name == "service-b"
