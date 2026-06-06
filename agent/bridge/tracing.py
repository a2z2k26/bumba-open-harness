"""Lightweight OTEL-style tracing with JSONL export.

No external dependencies — pure Python implementation.
Real OpenTelemetry can replace this later without API changes.
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generator


def generate_trace_id() -> str:
    """Generate a random 16-byte hex trace ID."""
    return os.urandom(16).hex()


def generate_span_id() -> str:
    """Generate a random 8-byte hex span ID."""
    return os.urandom(8).hex()


@dataclass
class Span:
    """A single trace span."""

    span_id: str
    trace_id: str
    parent_id: str | None
    name: str
    start_time: float
    end_time: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"  # "ok" | "error"
    events: list[dict[str, Any]] = field(default_factory=list)
    workflow_id: str | None = None  # Z4 workflow run correlation ID

    def to_dict(self) -> dict[str, Any]:
        """Serialize span to a dictionary for JSONL export."""
        d: dict[str, Any] = {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "attributes": self.attributes,
            "status": self.status,
            "events": self.events,
        }
        if self.workflow_id is not None:
            d["workflow_id"] = self.workflow_id
        return d

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """Add a timestamped event to this span."""
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })


class SpanContext:
    """Thread-local span context that tracks the current trace and parent span stack."""

    def __init__(self) -> None:
        self._local = threading.local()

    @property
    def _stack(self) -> list[Span]:
        if not hasattr(self._local, "stack"):
            self._local.stack = []
        return self._local.stack

    @property
    def trace_id(self) -> str | None:
        if not hasattr(self._local, "trace_id"):
            self._local.trace_id = None
        return self._local.trace_id

    @trace_id.setter
    def trace_id(self, value: str | None) -> None:
        self._local.trace_id = value

    def push(self, span: Span) -> None:
        """Push a span onto the parent stack."""
        self._stack.append(span)
        self.trace_id = span.trace_id

    def pop(self) -> Span | None:
        """Pop the top span from the parent stack."""
        stack = self._stack
        if not stack:
            return None
        span = stack.pop()
        if stack:
            self.trace_id = stack[-1].trace_id
        else:
            self.trace_id = None
        return span

    @property
    def current_span(self) -> Span | None:
        """Return the current (top) span, or None."""
        stack = self._stack
        return stack[-1] if stack else None

    @property
    def depth(self) -> int:
        """Return the current stack depth."""
        return len(self._stack)


class Tracer:
    """JSONL-based span tracer.

    Writes completed spans as newline-delimited JSON to the output file.
    Thread-safe via a write lock.
    """

    def __init__(
        self,
        service_name: str,
        output_path: str | Path | None = None,
    ) -> None:
        self.service_name = service_name
        if output_path is None:
            self.output_path = Path("data/traces.jsonl")
        else:
            self.output_path = Path(output_path)
        self._write_lock = threading.Lock()
        self._context = SpanContext()

    def start_span(
        self,
        name: str,
        parent: Span | None = None,
        attributes: dict[str, Any] | None = None,
        workflow_id: str | None = None,
    ) -> Span:
        """Start a new span.

        If parent is not provided, uses the current span from context.
        If workflow_id is supplied, it is set on this span and propagated
        automatically to all child spans created while it is on the stack.
        """
        if parent is not None:
            parent_id = parent.span_id
            trace_id = parent.trace_id
            # Inherit workflow_id from parent if not explicitly provided
            if workflow_id is None:
                workflow_id = parent.workflow_id
        elif self._context.current_span is not None:
            parent_id = self._context.current_span.span_id
            trace_id = self._context.current_span.trace_id
            if workflow_id is None:
                workflow_id = self._context.current_span.workflow_id
        else:
            parent_id = None
            trace_id = generate_trace_id()

        attrs = {"service.name": self.service_name}
        if attributes:
            attrs.update(attributes)

        span = Span(
            span_id=generate_span_id(),
            trace_id=trace_id,
            parent_id=parent_id,
            name=name,
            start_time=time.time(),
            attributes=attrs,
            workflow_id=workflow_id,
        )
        self._context.push(span)
        return span

    def end_span(self, span: Span) -> None:
        """End a span: set end_time and write to JSONL."""
        span.end_time = time.time()
        self._context.pop()
        self._write_span(span)

    @contextmanager
    def context_span(
        self,
        name: str,
        parent: Span | None = None,
        attributes: dict[str, Any] | None = None,
        workflow_id: str | None = None,
    ) -> Generator[Span, None, None]:
        """Context manager that starts and ends a span automatically.

        On exception, marks the span status as 'error' and records the
        exception as an event before re-raising.

        ``workflow_id`` is propagated to child spans automatically — set it
        on the root span of a workflow step invocation and all nested spans
        will carry the same correlation ID.
        """
        span = self.start_span(
            name, parent=parent, attributes=attributes, workflow_id=workflow_id
        )
        try:
            yield span
        except Exception as exc:
            span.status = "error"
            span.add_event("exception", {
                "exception.type": type(exc).__name__,
                "exception.message": str(exc),
            })
            raise
        finally:
            self.end_span(span)

    def _write_span(self, span: Span) -> None:
        """Write a completed span to the JSONL file (thread-safe)."""
        line = json.dumps(span.to_dict(), separators=(",", ":"))
        with self._write_lock:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_path, "a") as f:
                f.write(line + "\n")

    def get_recent_spans(self, limit: int = 10) -> list[Span]:
        """Return the most recently completed spans from the JSONL output file."""
        if not self.output_path.exists():
            return []
        spans: list[Span] = []
        try:
            lines = self.output_path.read_text().strip().splitlines()
            for raw in reversed(lines[-limit * 2:]):
                try:
                    data = json.loads(raw)
                    span = Span(
                        trace_id=data.get("trace_id", ""),
                        span_id=data.get("span_id", ""),
                        parent_id=data.get("parent_id"),
                        name=data.get("name", ""),
                        start_time=data.get("start_time", 0.0),
                        end_time=data.get("end_time"),
                        attributes=data.get("attributes", {}),
                        status=data.get("status", "ok"),
                        events=data.get("events", []),
                        workflow_id=data.get("workflow_id"),
                    )
                    span.duration_ms = data.get("duration_ms", 0.0)  # type: ignore[attr-defined]
                    spans.append(span)
                    if len(spans) >= limit:
                        break
                except (json.JSONDecodeError, KeyError):
                    continue
        except OSError:
            pass
        return spans


# ---------------------------------------------------------------------------
# Singleton registry
# ---------------------------------------------------------------------------

_tracers: dict[str, Tracer] = {}
_tracers_lock = threading.Lock()


def get_tracer(service_name: str, output_path: str | Path | None = None) -> Tracer:
    """Return a singleton Tracer for the given service name.

    Subsequent calls with the same service_name return the same instance
    (output_path is only used on the first call).
    """
    with _tracers_lock:
        if service_name not in _tracers:
            _tracers[service_name] = Tracer(service_name, output_path=output_path)
        return _tracers[service_name]


def reset_tracers() -> None:
    """Clear the singleton registry (for testing)."""
    with _tracers_lock:
        _tracers.clear()


# ---------------------------------------------------------------------------
# Startup phase helper — P6.4 (#1599)
# ---------------------------------------------------------------------------
# Some startup phases (config load, DB migrate) run BEFORE the bridge tracer
# exists. The pattern below captures wall-clock checkpoints during boot and
# emits a completed span retroactively once the tracer is constructed, so the
# operator can still see those phases in /api/traces. After the tracer exists,
# prefer ``tracer.context_span(...)`` for phases that haven't started yet.


def record_completed_span(
    tracer: "Tracer",
    name: str,
    start_time: float,
    end_time: float,
    attributes: dict[str, Any] | None = None,
    status: str = "ok",
) -> Span:
    """Emit a completed span with explicit start/end timestamps.

    Useful for retroactive recording of phases that ran before the tracer
    existed (e.g. early startup steps). The span is written directly to the
    tracer's JSONL sink — it is NOT pushed onto the thread-local context
    stack, so it never participates in parent/child nesting.

    Args:
        tracer: The Tracer instance to write through.
        name: Span name (e.g. ``"startup.config_load"``).
        start_time: Wall-clock seconds (``time.time()``) when the phase began.
        end_time: Wall-clock seconds (``time.time()``) when the phase ended.
            Must be >= start_time.
        attributes: Optional attributes dict; ``service.name`` is added
            automatically.
        status: ``"ok"`` (default) or ``"error"``.

    Returns:
        The Span dataclass that was written.
    """
    if end_time < start_time:
        raise ValueError(
            f"record_completed_span: end_time ({end_time}) "
            f"< start_time ({start_time})"
        )
    attrs: dict[str, Any] = {"service.name": tracer.service_name}
    if attributes:
        attrs.update(attributes)
    span = Span(
        span_id=generate_span_id(),
        trace_id=generate_trace_id(),
        parent_id=None,
        name=name,
        start_time=start_time,
        end_time=end_time,
        attributes=attrs,
        status=status,
    )
    tracer._write_span(span)  # noqa: SLF001 — by-design write-only API
    return span


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def format_span_tree(spans: list[Span]) -> str:
    """Format a list of spans as an indented tree string.

    Spans are organized by parent_id. Root spans (parent_id is None) are
    top-level; children are indented beneath their parents.

    Returns a multi-line string like:
        [2.35ms] request.handle (ok)
          [1.12ms] db.query (ok)
          [0.98ms] render.template (ok)
    """
    if not spans:
        return ""

    # Index spans by span_id for lookup
    by_id: dict[str, Span] = {s.span_id: s for s in spans}

    # Group children by parent_id
    children: dict[str | None, list[Span]] = {}
    for span in spans:
        children.setdefault(span.parent_id, []).append(span)

    # Sort children by start_time within each group
    for kids in children.values():
        kids.sort(key=lambda s: s.start_time)

    lines: list[str] = []

    def _render(span: Span, depth: int) -> None:
        indent = "  " * depth
        if span.end_time is not None:
            duration_ms = (span.end_time - span.start_time) * 1000
            duration_str = f"{duration_ms:.2f}ms"
        else:
            duration_str = "running"
        lines.append(f"{indent}[{duration_str}] {span.name} ({span.status})")
        for child in children.get(span.span_id, []):
            _render(child, depth + 1)

    # Render all root spans (those whose parent_id is None or not in our set)
    roots = [s for s in spans if s.parent_id is None or s.parent_id not in by_id]
    roots.sort(key=lambda s: s.start_time)
    for root in roots:
        _render(root, 0)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# OTEL-shape facade — E2.2 (#1239)
# ---------------------------------------------------------------------------
# Exposes the OpenTelemetry Python API surface (get_tracer / start_as_current_span)
# while routing through the existing Tracer.context_span(...) so the JSONL
# export at _write_span above remains the durable sink.
# Per E-O4: API package only, no SDK, no exporter.

try:
    import opentelemetry as _otel_pkg  # noqa: F401 — presence check only
    from opentelemetry import trace as otel_trace

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False


class OTELTracerFacade:
    """OTEL-shape facade over bridge.tracing.Tracer.

    Exposes ``start_as_current_span(name, attributes=...)`` matching the
    OpenTelemetry Python API contract.  Under the hood it calls
    ``Tracer.context_span(...)`` so the JSONL export at tracing.py:_write_span
    is the durable sink.  Per E-O4: no SDK, no exporter — API surface only.

    Instantiate via ``get_otel_tracer(name)``; do not construct directly.
    """

    def __init__(self, *, name: str, tracer: "Tracer") -> None:
        self._name = name
        self._tracer = tracer

    @contextmanager
    def start_as_current_span(
        self,
        name: str,
        *,
        attributes: dict[str, Any] | None = None,
    ) -> Generator[Span, None, None]:
        """Context manager mirroring ``opentelemetry.trace.Tracer.start_as_current_span``.

        Yields the underlying ``bridge.tracing.Span`` so callers can add
        attributes after the fact (e.g. winner scores from tool_shed).
        """
        with self._tracer.context_span(name, attributes=attributes or {}) as span:
            yield span


def get_otel_tracer(name: str, output_path: str | Path | None = None) -> OTELTracerFacade:
    """Return an OTEL-shape facade for the named service.

    Raises ``ImportError`` when ``opentelemetry-api`` is not installed,
    giving callers a clear failure mode rather than a silent no-op.

    Args:
        name: Logical service / component name (e.g. ``"bumba.tool_shed"``).
        output_path: Forwarded to ``get_tracer``; uses the default
            ``data/traces.jsonl`` when omitted.

    Returns:
        ``OTELTracerFacade`` wrapping the singleton ``Tracer`` for ``name``.
    """
    if not _OTEL_AVAILABLE:
        raise ImportError(
            "opentelemetry-api is required for get_otel_tracer(). "
            "Add opentelemetry-api>=1.20 to your dependencies."
        )
    return OTELTracerFacade(name=name, tracer=get_tracer(name, output_path=output_path))


def span_from_otel_context() -> "Span | None":
    """Bridge helper: read the current OTEL span context and return the underlying Span.

    Useful for sites that want the active Span without importing the facade
    directly.

    Returns:
        The current ``bridge.tracing.Span`` if one is active in this thread,
        otherwise ``None``.  Also returns ``None`` when ``opentelemetry-api``
        is not installed.
    """
    if not _OTEL_AVAILABLE:
        return None
    try:
        otel_span = otel_trace.get_current_span()
        if otel_span is None or not otel_span.is_recording():
            return None
        # The facade authors Bumba's Span via Tracer.context_span, which stores
        # it in the thread-local SpanContext stack.  The top of that stack is
        # the "current" span correlated with the OTEL context.
        from opentelemetry.trace import NonRecordingSpan  # type: ignore[import-untyped]

        if isinstance(otel_span, NonRecordingSpan):
            return None
    except Exception:  # pragma: no cover — defensive; OTEL API must not crash us
        return None
    # Fall back to the thread-local SpanContext top-of-stack.
    for _tracer in _tracers.values():
        span = _tracer._context.current_span
        if span is not None:
            return span
    return None
