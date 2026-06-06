"""Per-run telemetry for Zone 4 department execution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace as dataclass_replace

from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded


@dataclass(frozen=True)
class UsageTelemetry:
    input_tokens: int = 0
    output_tokens: int = 0
    request_count: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class RunTelemetry:
    department: str
    chief_name: str
    primary_model: str
    fallback_model: str | None = None
    fallback_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    request_count: int = 0
    duration_seconds: float = 0.0
    specialists_expected_min: int = 0
    specialists_returned: int = 0
    specialists_successful: int = 0
    surfaces_written: int = 0
    artifacts_written: int = 0
    failure_class: str | None = None
    extra: tuple[tuple[str, str], ...] = field(default_factory=tuple)


def usage_telemetry(usage: object | None) -> UsageTelemetry:
    """Return stable token/request counts from pydantic-ai usage objects."""
    if usage is None:
        return UsageTelemetry()

    return UsageTelemetry(
        input_tokens=_int_attr(usage, ("input_tokens", "request_tokens")),
        output_tokens=_int_attr(usage, ("output_tokens", "response_tokens")),
        request_count=_int_attr(usage, ("requests", "request_count")),
    )


def total_tokens_from_usage(usage: object | None) -> int:
    """Return total tokens using explicit total when available, else in+out."""
    if usage is None:
        return 0

    total = _int_attr(usage, ("total_tokens",))
    if total > 0:
        return total

    return usage_telemetry(usage).total_tokens


def normalize_failure_class(exc: BaseException | str | None) -> str | None:
    """Normalize known runtime failures into low-cardinality class names."""
    if exc is None:
        return None
    if isinstance(exc, UsageLimitExceeded):
        return "usage_limit_exceeded"
    if isinstance(exc, ModelHTTPError):
        return "model_http_error"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, str):
        return _to_snake(exc)
    return _to_snake(type(exc).__name__)


def telemetry_with_failure(
    telemetry: RunTelemetry | None,
    failure_class: str,
) -> RunTelemetry | None:
    """Set a failure class on telemetry unless one was already recorded."""
    if telemetry is None:
        return None
    if telemetry.failure_class:
        return telemetry
    return dataclass_replace(telemetry, failure_class=failure_class)


def render_telemetry_footer(telemetry: RunTelemetry) -> str:
    """Render a compact operator-facing telemetry footer."""
    parts = [
        f"chief={telemetry.chief_name}",
        f"primary={telemetry.primary_model}",
    ]
    if telemetry.fallback_model:
        parts.append(f"fallback={telemetry.fallback_model}")
    if telemetry.fallback_reason:
        parts.append(f"reason={telemetry.fallback_reason}")
    parts.extend(
        [
            f"tokens=in:{telemetry.input_tokens} out:{telemetry.output_tokens}",
            f"requests={telemetry.request_count}",
            f"duration={telemetry.duration_seconds:.1f}s",
            (
                "specialists="
                f"{telemetry.specialists_successful}/"
                f"{telemetry.specialists_expected_min}"
            ),
            f"returned={telemetry.specialists_returned}",
            f"surfaces={telemetry.surfaces_written}",
            f"artifacts={telemetry.artifacts_written}",
        ]
    )
    if telemetry.failure_class:
        parts.append(f"failure={telemetry.failure_class}")
    return "[run telemetry] " + " | ".join(parts)


def _int_attr(source: object, names: tuple[str, ...]) -> int:
    candidate = 0
    for name in names:
        value = getattr(source, name, 0)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            if value != 0:
                return value
            candidate = value
    return candidate


def _to_snake(value: str) -> str:
    text = value.strip()
    if not text:
        return "unknown"
    text = re.sub(r"(?<!^)(?=[A-Z])", "_", text).lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown"
