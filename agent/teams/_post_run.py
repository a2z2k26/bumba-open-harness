"""Pure post-run hygiene policy for Zone 4 team executions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from teams._run_telemetry import RunTelemetry
from teams._types import TeamResult

CONTEXT_CLEAR_INPUT_TOKEN_THRESHOLD = 200_000

RECOVERABLE_FAILURE_CLASSES = frozenset(
    {
        "model_http_error",
        "output_gate_violation",
        "timeout",
        "usage_limit_exceeded",
    }
)


@dataclass(frozen=True)
class PostRunDecision:
    """Policy decision for one completed Zone 4 run."""

    checkpoint: bool
    clear_message_history: bool
    input_tokens: int
    artifact_count: int
    failure_class: str | None
    manifest_path: str | None


def should_checkpoint(
    result: TeamResult,
    telemetry: RunTelemetry | None = None,
) -> bool:
    """Return True when a run has enough signal to preserve a checkpoint."""
    failure_class = failure_class_from_result(result, telemetry)
    if failure_class in RECOVERABLE_FAILURE_CLASSES:
        return True

    return any(
        (
            bool(result.manager_output.strip()),
            bool(result.error),
            bool(result.employee_results),
            bool(result.manifest_path),
            bool(result.memory_ref),
            artifact_count_from_result(result, telemetry) > 0,
            input_tokens_from_result(result, telemetry) > 0,
        )
    )


def should_clear_message_history(
    *,
    input_tokens: int,
    failure_class: str | None,
    artifact_count: int,
) -> bool:
    """Return True when warm message history should be cleared post-run."""
    if failure_class == "usage_limit_exceeded":
        return True
    if (
        input_tokens >= CONTEXT_CLEAR_INPUT_TOKEN_THRESHOLD
        and artifact_count > 0
    ):
        return True
    return False


def decide_post_run_hygiene(
    result: TeamResult,
    telemetry: RunTelemetry | None = None,
) -> PostRunDecision:
    """Build a deterministic post-run hygiene decision."""
    resolved_telemetry = telemetry or result.telemetry
    input_tokens = input_tokens_from_result(result, resolved_telemetry)
    artifact_count = artifact_count_from_result(result, resolved_telemetry)
    failure_class = failure_class_from_result(result, resolved_telemetry)
    return PostRunDecision(
        checkpoint=should_checkpoint(result, resolved_telemetry),
        clear_message_history=should_clear_message_history(
            input_tokens=input_tokens,
            failure_class=failure_class,
            artifact_count=artifact_count,
        ),
        input_tokens=input_tokens,
        artifact_count=artifact_count,
        failure_class=failure_class,
        manifest_path=result.manifest_path,
    )


def input_tokens_from_result(
    result: TeamResult,
    telemetry: RunTelemetry | None = None,
) -> int:
    """Resolve input tokens from telemetry, falling back to TeamResult total."""
    telemetry_input = _non_negative_int_attr(telemetry, "input_tokens")
    if telemetry_input is not None:
        return telemetry_input

    return max(0, result.total_tokens // 2)


def artifact_count_from_result(
    result: TeamResult,
    telemetry: RunTelemetry | None = None,
) -> int:
    """Resolve artifact count from telemetry, falling back to the manifest."""
    telemetry_artifacts = _non_negative_int_attr(telemetry, "artifacts_written")
    manifest_artifacts = artifact_count_from_manifest(result.manifest_path)
    if telemetry_artifacts is None:
        return manifest_artifacts
    return max(telemetry_artifacts, manifest_artifacts)


def artifact_count_from_manifest(manifest_path: str | Path | None) -> int:
    """Return the manifest artifact count, or 0 when unavailable."""
    if manifest_path is None:
        return 0

    path = Path(manifest_path).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        return 0
    return len(artifacts)


def failure_class_from_result(
    result: TeamResult,
    telemetry: RunTelemetry | None = None,
) -> str | None:
    """Resolve the low-cardinality failure class for post-run policy."""
    telemetry_failure = getattr(telemetry, "failure_class", None)
    if isinstance(telemetry_failure, str) and telemetry_failure:
        return telemetry_failure

    error = (result.error or "").lower().replace(" ", "_")
    if "usage_limit_exceeded" in error or "usagelimitexceeded" in error:
        return "usage_limit_exceeded"
    if "usage_limit" in error and "exceed" in error:
        return "usage_limit_exceeded"
    return None


def _non_negative_int_attr(obj: object | None, name: str) -> int | None:
    value = getattr(obj, name, None)
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None
