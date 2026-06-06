"""Common tool functions available to all departments."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from pydantic_ai import RunContext

from teams._types import BridgeDeps

log = logging.getLogger(__name__)


async def _run_subprocess(
    cmd: list[str],
    cwd: Optional[str] = None,
    timeout: int = 120,
) -> tuple[str, int]:
    """Run a subprocess, capture stdout+stderr, return (output, returncode)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
        )
    except FileNotFoundError:
        executable = cmd[0] if cmd else "<empty command>"
        log.warning("tool subprocess executable unavailable: %s", executable)
        return (f"COMMAND_UNAVAILABLE: executable '{executable}' not found", 127)
    try:
        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return (f"TIMEOUT after {timeout}s", 124)
    output = stdout_bytes.decode("utf-8", errors="replace")
    return (output, proc.returncode or 0)


async def read_file(ctx: RunContext[BridgeDeps], path: str) -> str:
    """Read a file from the repo. Returns file contents or error message."""
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return f"ERROR: file not found: {path}"
    try:
        return p.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {e}"


async def search_knowledge(ctx: RunContext[BridgeDeps], query: str) -> str:
    """Search the shared knowledge store for relevant entries."""
    try:
        results = await ctx.deps.knowledge_search(query, limit=5)
        return "\n\n".join(str(r) for r in results)
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {e}"


async def pending_handoffs(ctx: RunContext[BridgeDeps], department: str) -> str:
    """List all unexpired handoff envelopes waiting for *department*.

    Returns a formatted summary of inbound handoffs so the manager can
    discover work waiting for it without needing a specific correlation_id.
    Returns "No pending handoffs" if the queue is empty.

    Sprint B-S.2.
    """
    from teams._handoff import list_pending_handoffs

    try:
        envelopes = await list_pending_handoffs(ctx.deps.memory_store, department)
    except Exception as e:  # noqa: BLE001
        return f"ERROR listing pending handoffs: {e}"

    if not envelopes:
        return f"No pending handoffs for department={department!r}"

    lines = [f"Pending handoffs for {department!r} ({len(envelopes)} found):"]
    for env in envelopes:
        lines.append(
            f"  - {env.correlation_id[:8]}... from={env.from_department!r} "
            f"task={env.task[:80]!r} expires={env.expires_at}"
        )
    return "\n".join(lines)
