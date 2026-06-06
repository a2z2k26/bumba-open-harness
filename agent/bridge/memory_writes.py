"""memory_writes.py — Uniform write-receipt log for all silent memory stores.

Sprint D2.3 — ships MemoryWriteReceipt, emit(), and tail() helpers.
Every silent memory store calls emit() at its write entry point so the
operator can answer "what did Bumba write to memory in the last hour?"
with one command (/memory_writes) instead of grepping multiple JSONL
files and SQLite tables.

Atomic-append pattern sourced from cost_tracker._atomic_append (line 217).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

_PATH = Path("data/memory-writes.jsonl")  # rotated by resource_manager at 50MB

Subsystem = Literal[
    "conversation",
    "knowledge",
    "temporal_knowledge",
    "bumba_memory_mcp",
    "memory_file",
    "z4_conversation_log",
]

Op = Literal["insert", "update", "delete", "rollback"]


@dataclass(frozen=True)
class MemoryWriteReceipt:
    """Immutable record of a single memory write across any subsystem."""

    timestamp: str  # ISO-8601 UTC
    subsystem: str  # one of Subsystem
    op: str  # one of Op
    key: str  # short identifier (knowledge key, session_id:role, etc.)
    bytes: int  # approximate payload size
    actor: str = "agent"  # agent | service:<name> | operator | tier_b_approved
    notes: str = ""  # optional, ≤ 200 chars

    @classmethod
    def now(
        cls,
        *,
        subsystem: str,
        op: str,
        key: str,
        payload_bytes: int,
        actor: str = "agent",
        notes: str = "",
    ) -> "MemoryWriteReceipt":
        """Construct a receipt stamped at the current UTC time."""
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            subsystem=subsystem,
            op=op,
            key=key[:120],
            bytes=int(payload_bytes),
            actor=actor,
            notes=notes[:200],
        )


def emit(receipt: MemoryWriteReceipt, *, path: Path = _PATH) -> None:
    """Append one JSONL line atomically. Never raises — logs at WARNING.

    Uses os.open with O_APPEND so concurrent writers cannot tear a line
    (POSIX guarantees atomicity for writes up to PIPE_BUF on O_APPEND fds).
    The underlying memory write always proceeds regardless of emit failure.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(asdict(receipt)) + "\n"
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except Exception as exc:
        log.warning("memory_writes.emit failed (%s): %s", receipt.subsystem, exc)


def tail(
    n: int = 20,
    *,
    subsystem: str | None = None,
    path: Path = _PATH,
) -> list[MemoryWriteReceipt]:
    """Return up to *n* most-recent receipts (newest first), optionally filtered.

    Whole-file read is acceptable — JSONL stays small (rotated at 50 MB).
    """
    if not path.exists():
        return []
    out: list[MemoryWriteReceipt] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        log.warning("memory_writes.tail read failed: %s", exc)
        return []
    for raw in reversed(lines):
        if not raw.strip():
            continue
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if subsystem and d.get("subsystem") != subsystem:
            continue
        try:
            out.append(MemoryWriteReceipt(**d))
        except TypeError:
            continue
        if len(out) >= n:
            break
    return out
