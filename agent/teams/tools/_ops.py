"""Ops department tool functions."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic_ai import RunContext

from teams._handoff import load_handoff
from teams._types import BridgeDeps
from teams.tools._common import _run_subprocess

log = logging.getLogger(__name__)

OPS_TOOL_OUTPUT_MAX_CHARS = 12_000


def _cap_tool_output(label: str, output: str) -> str:
    """Return a model-safe tool payload while keeping the newest log text."""
    header = f"=== {label} ===\n"
    payload = f"{header}{output}"
    if len(payload) <= OPS_TOOL_OUTPUT_MAX_CHARS:
        return payload

    marker = (
        f"[...truncated to {OPS_TOOL_OUTPUT_MAX_CHARS} chars from "
        f"{len(payload)} chars; kept newest log tail...]\n"
    )
    tail_chars = OPS_TOOL_OUTPUT_MAX_CHARS - len(header) - len(marker)
    if tail_chars <= 0:
        return payload[:OPS_TOOL_OUTPUT_MAX_CHARS]
    return f"{header}{marker}{output[-tail_chars:]}"


async def check_service_status(
    ctx: RunContext[BridgeDeps], service_name: str
) -> str:
    """Check the status of a launchd service on the Mac Mini."""
    if not service_name.startswith("com.bumba."):
        return f"Refused: only com.bumba.* services allowed (got {service_name!r})"

    output, code = await _run_subprocess(
        ["launchctl", "list", service_name],
        timeout=10,
    )
    if code != 0:
        return f"Service not found or not loaded: {service_name}"
    return output[-2000:]


async def tail_log(
    ctx: RunContext[BridgeDeps], service: str, lines: int = 50
) -> str:
    """Tail the last N lines of a service's log file."""
    lines = max(10, min(500, lines))
    candidates = [
        Path(f"/opt/bumba-harness/logs/{service}.log"),
        Path(f"/opt/bumba-harness/logs/{service}-stdout.log"),
        Path(f"/opt/bumba-harness/logs/{service}-stderr.log"),
    ]
    for path in candidates:
        if path.exists():
            output, _ = await _run_subprocess(
                ["tail", "-n", str(lines), str(path)],
                timeout=10,
            )
            return _cap_tool_output(str(path), output)
    return f"No log file found for: {service}"


async def query_metrics(
    ctx: RunContext[BridgeDeps], metric: str, window_minutes: int = 60
) -> str:
    """Query a named metric from the bridge metrics store."""
    try:
        result = await ctx.deps.memory_store.get(f"metric:{metric}:latest")
        if not result:
            return f"Metric not found: {metric}"
        return f"Metric {metric}: {result}"
    except Exception as e:  # noqa: BLE001
        log.exception("query_metrics failed")
        return f"ERROR: {e}"


async def continue_handoff(
    ctx: RunContext[BridgeDeps], correlation_id: str
) -> str:
    """Load a HandoffEnvelope from shared memory by correlation_id.

    Returns the envelope contents as formatted task context that the
    receiving department agent can act on.

    Sprint B-S.1: expired envelopes are rejected with an explicit error message
    so the manager knows not to act on stale context.
    """
    envelope = await load_handoff(correlation_id, ctx.deps.memory_store)
    if envelope is None:
        return f"No handoff found for correlation_id={correlation_id}"

    # B-S.1: reject expired envelopes
    if envelope.is_expired():
        return (
            f"Handoff {correlation_id} has expired (expires_at={envelope.expires_at}). "
            "Do not act on this handoff — request a fresh one from the sending department."
        )

    return (
        f"Handoff from {envelope.from_department} \u2192 {envelope.to_department}\n"
        f"Task: {envelope.task}\n"
        f"Findings: {envelope.findings}\n"
        f"Created: {envelope.created_at}\n"
        f"Expires: {envelope.expires_at}\n"
        f"Files: {', '.join(envelope.context_files) if envelope.context_files else 'none'}"
    )
